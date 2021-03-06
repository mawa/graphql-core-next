import re
from typing import Any, Iterable, List, Mapping, Optional, cast

from ..language import (
    BooleanValueNode,
    EnumValueNode,
    FloatValueNode,
    IntValueNode,
    ListValueNode,
    NameNode,
    NullValueNode,
    ObjectFieldNode,
    ObjectValueNode,
    StringValueNode,
    ValueNode,
)
from ..pyutils import is_nullish, is_invalid
from ..type import (
    GraphQLID,
    GraphQLInputType,
    GraphQLInputObjectType,
    GraphQLList,
    GraphQLNonNull,
    is_enum_type,
    is_input_object_type,
    is_list_type,
    is_non_null_type,
    is_scalar_type,
)

__all__ = ["ast_from_value"]

_re_integer_string = re.compile("^-?(0|[1-9][0-9]*)$")


def ast_from_value(value: Any, type_: GraphQLInputType) -> Optional[ValueNode]:
    """Produce a GraphQL Value AST given a Python value.

    A GraphQL type must be provided, which will be used to interpret different
    Python values.

    | JSON Value    | GraphQL Value        |
    | ------------- | -------------------- |
    | Object        | Input Object         |
    | Array         | List                 |
    | Boolean       | Boolean              |
    | String        | String / Enum Value  |
    | Number        | Int / Float          |
    | Mixed         | Enum Value           |
    | null          | NullValue            |

    """
    if is_non_null_type(type_):
        type_ = cast(GraphQLNonNull, type_)
        ast_value = ast_from_value(value, type_.of_type)
        if isinstance(ast_value, NullValueNode):
            return None
        return ast_value

    # only explicit None, not INVALID or NaN
    if value is None:
        return NullValueNode()

    # INVALID or NaN
    if is_invalid(value):
        return None

    # Convert Python list to GraphQL list. If the GraphQLType is a list, but
    # the value is not a list, convert the value using the list's item type.
    if is_list_type(type_):
        type_ = cast(GraphQLList, type_)
        item_type = type_.of_type
        if isinstance(value, Iterable) and not isinstance(value, str):
            value_nodes = [
                ast_from_value(item, item_type) for item in value  # type: ignore
            ]
            return ListValueNode(values=value_nodes)
        return ast_from_value(value, item_type)  # type: ignore

    # Populate the fields of the input object by creating ASTs from each value
    # in the Python dict according to the fields in the input type.
    if is_input_object_type(type_):
        if value is None or not isinstance(value, Mapping):
            return None
        type_ = cast(GraphQLInputObjectType, type_)
        field_nodes: List[ObjectFieldNode] = []
        append_node = field_nodes.append
        for field_name, field in type_.fields.items():
            if field_name in value:
                field_value = ast_from_value(value[field_name], field.type)
                if field_value:
                    append_node(
                        ObjectFieldNode(
                            name=NameNode(value=field_name), value=field_value
                        )
                    )
        return ObjectValueNode(fields=field_nodes)

    if is_scalar_type(type_) or is_enum_type(type_):
        # Since value is an internally represented value, it must be serialized
        # to an externally represented value before converting into an AST.
        serialized = type_.serialize(value)  # type: ignore
        if is_nullish(serialized):
            return None

        # Others serialize based on their corresponding Python scalar types.
        if isinstance(serialized, bool):
            return BooleanValueNode(value=serialized)

        # Python ints and floats correspond nicely to Int and Float values.
        if isinstance(serialized, int):
            return IntValueNode(value=f"{serialized:d}")
        if isinstance(serialized, float):
            return FloatValueNode(value=f"{serialized:g}")

        if isinstance(serialized, str):
            # Enum types use Enum literals.
            if is_enum_type(type_):
                return EnumValueNode(value=serialized)

            # ID types can use Int literals.
            if type_ is GraphQLID and _re_integer_string.match(serialized):
                return IntValueNode(value=serialized)

            return StringValueNode(value=serialized)

        raise TypeError(f"Cannot convert value to AST: {serialized!r}")

    raise TypeError(f"Unknown type: {type_!r}.")
