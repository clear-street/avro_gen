import os

from avro import schema
from . import namespace as ns_
from . import logical
import six
import keyword

if six.PY3:
    long = int


PRIMITIVE_TYPES = {
    'null',
    'boolean',
    'int',
    'long',
    'float',
    'double',
    'bytes',
    'string'
}
__PRIMITIVE_TYPE_MAPPING = {
    'null': '',
    'boolean': bool,
    'int': int,
    'long': long,
    'float': float,
    'double': float,
    'bytes': bytes,
    'string': str,
}

def clean_fullname(fullname):
    if six.PY3:
        return fullname.lstrip('.')
    return fullname


def convert_default(full_name, idx, do_json=True):
    if do_json:
        return (f'_json_converter.from_json_object({full_name}Class.RECORD_SCHEMA.fields[{idx}].default,'
               + f' writers_schema={full_name}Class.RECORD_SCHEMA.fields[{idx}].type)')
    else:
        return f'SCHEMA.field_map["{idx}"].default'


def write_defaults(record, writer, my_full_name=None, use_logical_types=False, init=False):
    """
    Write concrete record class's constructor part which initializes fields with default values
    :param schema.RecordSchema record: Avro RecordSchema whose class we are generating
    :param TabbedWriter writer: Writer to write to
    :param str my_full_name: Full name of the RecordSchema we are writing. Should only be provided for protocol requests.
    :return:
    """
    i = 0
    my_full_name = my_full_name or clean_fullname(record.fullname)

    something_written = False
    for field in record.fields:
        f_name = field.name
        if keyword.iskeyword(field.name):
            f_name =  field.name + get_field_type_name(field.type, use_logical_types)
        default_type, nullable = find_type_of_default(field.type)
        default_written = False
        if field.has_default:
            if use_logical_types and default_type.props.get('logicalType') \
                    and default_type.props.get('logicalType') in logical.DEFAULT_LOGICAL_TYPES:
                lt = logical.DEFAULT_LOGICAL_TYPES[default_type.props.get('logicalType')]
                v = lt.initializer(convert_default(my_full_name,
                                                   idx=i,
                                                   do_json=isinstance(default_type,
                                                   schema.RecordSchema)))
                print(f'Is logical types schema: {f_name}\t{v}')
                writer.write(f'\nself.{f_name} = {v}')
                default_written = True
            elif isinstance(default_type, schema.RecordSchema):
                my_full_name = my_full_name.split('.')[-1]
                d = convert_default(idx=i, full_name=my_full_name, do_json=True)
                print(f'Is record schema: {f_name}\t{field.name}\t{my_full_name}\t{d}')
                writer.write(f'\nself.{f_name} = {field.name.capitalize()}Class({d})')
                default_written = True
            elif isinstance(default_type, (schema.PrimitiveSchema, schema.EnumSchema, schema.FixedSchema)):
                d = convert_default(full_name=my_full_name, idx=f_name, do_json=False)
                print(f'Is other schema: {f_name}\t{d}')
                writer.write(f'\nself.{f_name} = {d}')
                default_written = True

        if not default_written:
            default_written = True
            if nullable:
                writer.write(f'\nself.{f_name} = None')
            elif use_logical_types and default_type.props.get('logicalType') \
                    and default_type.props.get('logicalType') in logical.DEFAULT_LOGICAL_TYPES:
                lt = logical.DEFAULT_LOGICAL_TYPES[default_type.props.get('logicalType')]
                writer.write('\nself.{f_name} = {default}'.format(name=f_name,
                                                                default=lt.initializer()))
            elif isinstance(default_type, schema.PrimitiveSchema) and not default_type.props.get('logicalType'):
                d = get_primitive_field_initializer(default_type)
                writer.write(f'\nself.{f_name} = {d}')
            elif isinstance(default_type, schema.EnumSchema):
                f = clean_fullname(default_type.name)
                s = default_type.symbols[0]
                writer.write(f'\nself.{f_name} = {f}Class.{s}')
            elif isinstance(default_type, schema.MapSchema):
                writer.write(f'\nself.{f_name} = dict()')
            elif isinstance(default_type, schema.ArraySchema):
                writer.write(f'\nself.{f_name} = list()')
            elif isinstance(default_type, schema.FixedSchema):
                writer.write(f'\nself.{f_name}: str = str()')
            elif isinstance(default_type, schema.RecordSchema):
                f = clean_fullname(default_type.name)
                writer.write(f'\nself.{f_name} = {f}Class()')
            else:
                default_written = False
        something_written = something_written or default_written
        i += 1
    if not something_written:
        writer.write('\npass')

def write_setters(record, writer, use_logical_types=False):
    writer.write('\nfield_names = [')
    for field in record.fields:
        f_name = field.name
        if keyword.iskeyword(field.name):
            f_name =  field.name + get_field_type_name(field.type, use_logical_types)
        writer.write(f'"{f_name}", ')
    writer.write(']\n')

    writer.write('if set(inner_dict.keys()) - set(field_names):\n')
    writer.write('    err = set(inner_dict.keys()) - set(field_names)\n')
    writer.write('    raise KeyError(f"Keys from provided object are not subset of object params in {type(self).__name__}: {err}")\n')

    for field in record.fields:
        f_name = field.name
        if keyword.iskeyword(field.name):
            f_name =  field.name + get_field_type_name(field.type, use_logical_types)
        writer.write(f'self.{f_name} = inner_dict.get("{f_name}")\n')

def write_fields(record, writer, use_logical_types):
    """
    Write field definitions for a given RecordSchema
    :param schema.RecordSchema record: Avro RecordSchema we are generating
    :param TabbedWriter writer: Writer to write to
    :return:
    """
    writer.write('\n\n')
    for field in record.fields:  # type: schema.Field
        write_field(field, writer, use_logical_types)


def write_field(field, writer, use_logical_types):
    """
    Write a single field definition
    :param field:
    :param writer:
    :return:
    """
    name = field.name
    if keyword.iskeyword(field.name):
        name =  field.name + get_field_type_name(field.type, use_logical_types)
    writer.write('''
@property
def {name}(self) -> {ret_type_name}:
    return self._inner_dict.get('{raw_name}')


@{name}.setter
def {name}(self, value: {ret_type_name}):
    self._inner_dict['{raw_name}'] = value

'''.format(name=name, raw_name=field.name, ret_type_name=get_field_type_name(field.type, use_logical_types)))


def get_primitive_field_initializer(field_schema):
    """
    Gets a python code string which represents a type initializer for a primitive field.
    Used for required fields where no default is provided. Output will look like "int()" or similar
    :param schema.PrimitiveSchema field_schema:
    :return:
    """

    if field_schema.type == 'null':
        return 'None'
    return get_field_type_name(field_schema, False) + "()"


def get_field_type_name(field_schema, use_logical_types):
    """
    Gets a python type-hint for a given schema
    :param schema.Schema field_schema:
    :return: String containing python type hint
    """
    if use_logical_types and field_schema.props.get('logicalType'):
        from avrogen.logical import DEFAULT_LOGICAL_TYPES
        lt = DEFAULT_LOGICAL_TYPES.get(field_schema.props.get('logicalType'))
        if lt:
            return lt.typename()

    if isinstance(field_schema, schema.PrimitiveSchema):
        if field_schema.fullname == 'null':
            return ''
        return __PRIMITIVE_TYPE_MAPPING[field_schema.fullname].__name__
    elif isinstance(field_schema, schema.FixedSchema):
        return 'bytes'
    elif isinstance(field_schema, schema.NamedSchema):
        return field_schema.name + 'Class'
    elif isinstance(field_schema, schema.ArraySchema):
        return 'List[' + get_field_type_name(field_schema.items, use_logical_types) + ']'
    elif isinstance(field_schema, schema.MapSchema):
        return 'Dict[str, ' + get_field_type_name(field_schema.values, use_logical_types) + ']'
    elif isinstance(field_schema, schema.UnionSchema):
        type_names = [get_field_type_name(x, use_logical_types) for x in field_schema.schemas if
                      get_field_type_name(x, use_logical_types)]
        if len(type_names) > 1:
            return ' | '.join(type_names)
        elif len(type_names) == 1:
            return type_names[0]
        return ''


def find_type_of_default(field_type):
    """
    Returns full name of an avro type of the field's default value
    :param schema.Schema field_type:
    :return:
    """

    if isinstance(field_type, schema.UnionSchema):
        non_null_types = [s for s in field_type.schemas if s.type != 'null']
        if non_null_types:
            type_, nullable = find_type_of_default(non_null_types[0])
            nullable = nullable or any(
                f for f in field_type.schemas if isinstance(f, schema.PrimitiveSchema) and f.fullname == 'null')
        else:
            type_, nullable = field_type.schemas[0], True
        return type_, nullable
    elif isinstance(field_type, schema.PrimitiveSchema):
        return field_type, field_type.fullname == 'null'
    else:
        return field_type, False


def start_namespace(current, target, writer):
    """
    Writes a new class corresponding to the target namespace to the schema file and
     closes the prior namespace
    :param tuple[str] current: Current namespace
    :param tuple[str] target: Target namespace we need to generate classes for
    :param TabbedWriter writer:
    :return:
    """

    i = 0
    while i < min(len(current), len(target)) and current[i] == target[i]:
        i += 1

    writer.write('\n\n')
    writer.set_tab(0)
    writer.write('\n')
    for component in target[i:]:
        writer.write('class {name}(object):'.format(name=component))
        writer.tab()
        writer.write('\n')


def write_preamble(writer, use_logical_types, custom_imports):
    """
    Writes a preamble of the file containing schema classes
    :param  writer:
    :return:
    """
    writer.write('from __future__ import annotations\n')
    writer.write('import json\n')
    writer.write('import os.path\n')
    writer.write('import decimal\n')
    writer.write('import datetime\n')
    writer.write('import six\n')

    for cs in (custom_imports or []):
        writer.write(f'import {cs}\n')
    writer.write('from avrogen.dict_wrapper import DictWrapper\n')
    writer.write('from avrogen import avrojson\n')
    if use_logical_types:
        writer.write('from avrogen import logical\n')
    writer.write('from avro.schema import SchemaFromJSONData as make_avsc_object\n')
    writer.write('from avro import schema as avro_schema\n')
    writer.write('from typing import List, Dict\n')
    writer.write('\n')


def write_read_file(writer):
    """
    Write a function which reads our schema or protocol
    :param writer:
    :return:
    """
    writer.write('\ndef __read_file(file_name):')
    with writer.indent():
        writer.write('\nwith open(file_name, "r") as f:')
        with writer.indent():
            writer.write('\nreturn f.read()\n')


def write_get_schema(writer):
    """
    Write get_schema_type which is used by concrete classes to resolve their own RecordSchemas
    :param writer:
    :return:
    """
    writer.write('\n__SCHEMAS = {}\n\n\n')
    writer.write('def get_schema_type(fullname):')
    with writer.indent():
        writer.write('\nreturn __SCHEMAS.get(fullname)\n\n')


def write_reader_impl(record_types, writer, use_logical_types):
    """
    Write specific reader implementation
    :param list[schema.RecordSchema] record_types:
    :param writer:
    :return:
    """
    writer.write('\n\n\nclass SpecificDatumReader(%s):' % (
        'DatumReader' if not use_logical_types else 'logical.LogicalDatumReader'))
    with writer.indent():
        writer.write('\nSCHEMA_TYPES = {')
        with writer.indent():
            for t in record_types:
                writer.write('\n"{t_class}": {t_class}Class,'.format(t_class=t.split('.')[-1]))

        writer.write('\n}')
        writer.write('\n\n\ndef __init__(self, readers_schema=None, **kwargs):')
        with writer.indent():
            writer.write('\nwriters_schema = kwargs.pop("writers_schema", readers_schema)')
            writer.write('\nwriters_schema = kwargs.pop("writer_schema", writers_schema)')
            writer.write('\nsuper(SpecificDatumReader, self).__init__(writers_schema, readers_schema, **kwargs)')

        writer.write('\n\n\ndef read_record(self, writers_schema, readers_schema, decoder):')
        with writer.indent():
            writer.write(
                '\nresult = super(SpecificDatumReader, self).read_record(writers_schema, readers_schema, decoder)')
            writer.write('\n\nif readers_schema.fullname in SpecificDatumReader.SCHEMA_TYPES:')
            with writer.indent():
                writer.write('\nresult = SpecificDatumReader.SCHEMA_TYPES[readers_schema.fullname](result)')
            writer.write('\n\nreturn result')


def generate_namespace_modules(names, output_folder):
    """
    Generate python modules corresponding to schema/protocol namespaces.

    :param names:
    :param output_folder:
    :return: Dictinoary of (namespace, list(name))
    :rtype: dict[str, list[str]]
    """
    ns_dict = {}
    for name in names:
        name_parts = name.split('.')
        full_path = output_folder
        for part in name_parts[:-1]:
            full_path = os.path.join(full_path, part)
            if not os.path.isdir(full_path):
                os.mkdir(full_path)
                # make sure __init__.py is created for every namespace level
                with open(os.path.join(full_path, "__init__.py"), "w+"): pass

        ns = '.'.join(name_parts[:-1])
        if not ns in ns_dict:
            ns_dict[ns] = []
        ns_dict[ns].append(name_parts[-1])
    return ns_dict


def write_schema_record(record, writer, use_logical_types):
    """
    Writes class representing Avro record schema
    :param avro.schema.RecordSchema record:
    :param TabbedWriter writer:
    :return:
    """

    _, type_name = ns_.split_fullname(record.fullname)
    writer.write('''\nclass {name}Class(DictWrapper):'''.format(name=type_name))

    with writer.indent():
        writer.write('\nRECORD_SCHEMA = get_schema_type("%s")' % record.name)

        writer.write('\n\ndef __init__(self, inner_dict=None):')
        with writer.indent():
            writer.write('\n')
            writer.write('super({name}Class, self).__init__(inner_dict)'.format(name=record.name))

            writer.write('\nif inner_dict is None:')
            with writer.indent():
                write_defaults(record, writer, use_logical_types=use_logical_types)
            writer.write('\nelse:')
            with writer.indent():
                write_setters(record, writer)
        write_fields(record, writer, use_logical_types)


def write_enum(enum, writer):
    """
    Write class representing Avro enum schema
    :param schema.EnumSchema enum:
    :param TabbedWriter writer:
    :return:
    """
    _, type_name = ns_.split_fullname(enum.fullname)
    writer.write('''\nclass {name}Class(object):'''.format(name=type_name))

    with writer.indent():
        writer.write('\n')
        for field in enum.symbols:
            writer.write('{name} = "{name}"\n'.format(name=field))
        writer.write('\n')
