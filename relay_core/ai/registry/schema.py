"""Tool argument schemas from type hints, in the closed schema subset that Relay action contracts validate."""
import enum
import inspect
import types
from typing import Literal, Union, get_args, get_origin, get_type_hints, is_typeddict

PRIMITIVES = {str: 'string', int: 'integer', float: 'number', bool: 'boolean'}


def build_schema(function) -> dict:
    """A closed object schema of every parameter except the keyword-only `ctx`. Unsupported hints raise."""
    from relay_core.flows.action_contracts import check_schema
    hints = get_type_hints(function, include_extras=True)
    properties, required = {}, []
    for name, parameter in inspect.signature(function).parameters.items():
        if name == 'ctx':
            continue
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD) or name not in hints:
            raise TypeError(f'Tool parameter {name} needs a named, typed argument')
        properties[name], optional = parameter_schema(hints[name])
        if parameter.default is inspect.Parameter.empty and not optional:
            required.append(name)
    schema = {'type': 'object', 'properties': properties, 'additionalProperties': False}
    if required:
        schema['required'] = required
    check_schema(schema)
    return schema


def parameter_schema(hint) -> tuple[dict, bool]:
    """The schema of one hint and whether it is Optional; Annotated text becomes the description."""
    description = None
    hint, optional = unwrap_optional(hint)
    if hasattr(hint, '__metadata__'):
        description = next((item for item in hint.__metadata__ if isinstance(item, str)), None)
        hint, inner_optional = unwrap_optional(hint.__origin__)
        optional = optional or inner_optional
    schema = type_schema(hint)
    if description:
        schema['description'] = description
    return schema, optional


def unwrap_optional(hint):
    if get_origin(hint) not in (Union, types.UnionType) or type(None) not in get_args(hint):
        return hint, False
    remaining = [item for item in get_args(hint) if item is not type(None)]
    if len(remaining) != 1:
        raise TypeError('A tool parameter may be Optional of one type only')
    return remaining[0], True


def type_schema(hint) -> dict:
    origin = get_origin(hint)
    if hint in PRIMITIVES:
        return {'type': PRIMITIVES[hint]}
    if origin is Literal:
        return enum_schema(list(get_args(hint)))
    if isinstance(hint, type) and issubclass(hint, enum.Enum):
        return enum_schema([member.value for member in hint])
    if origin is list and get_args(hint):
        return {'type': 'array', 'items': type_schema(get_args(hint)[0])}
    if is_typeddict(hint):
        fields = get_type_hints(hint, include_extras=True)
        schema = {'type': 'object', 'properties': {name: parameter_schema(value)[0] for name, value in fields.items()},
                  'additionalProperties': False}
        if hint.__required_keys__:
            schema['required'] = [name for name in fields if name in hint.__required_keys__]
        return schema
    raise TypeError(f'Unsupported tool parameter type: {hint!r}')


def enum_schema(values: list) -> dict:
    kinds = {type(value) for value in values}
    if len(kinds) != 1 or next(iter(kinds)) not in PRIMITIVES:
        raise TypeError('Tool choices must share one primitive type')
    return {'type': PRIMITIVES[kinds.pop()], 'enum': values}
