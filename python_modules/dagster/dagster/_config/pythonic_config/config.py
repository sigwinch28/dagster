import re
from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Set,
    Type,
    cast,
)

from pydantic import BaseModel
from typing_extensions import TypeVar

import dagster._check as check
from dagster import (
    Field as DagsterField,
    Shape,
)
from dagster._config.field_utils import (
    EnvVar,
    IntEnvVar,
    Permissive,
)
from dagster._core.definitions.definition_config_schema import (
    DefinitionConfigSchema,
)
from dagster._core.errors import (
    DagsterInvalidConfigDefinitionError,
    DagsterInvalidDefinitionError,
    DagsterInvalidInvocationError,
    DagsterInvalidPythonicConfigDefinitionError,
)
from dagster._utils.cached_method import CACHED_METHOD_FIELD_SUFFIX

from .attach_other_object_to_context import (
    IAttachDifferentObjectToOpContext as IAttachDifferentObjectToOpContext,
)
from .conversion_utils import _convert_pydantic_field, safe_is_subclass
from .pydantic_compat_layer import (
    USING_PYDANTIC_2,
    ModelFieldCompat,
    model_config,
    model_fields,
)
from .typing_utils import BaseConfigMeta

try:
    from functools import cached_property  # type: ignore  # (py37 compat)
except ImportError:

    class cached_property:
        pass


INTERNAL_MARKER = "__internal__"

# ensure that this ends with the internal marker so we can do a single check
assert CACHED_METHOD_FIELD_SUFFIX.endswith(INTERNAL_MARKER)


def _is_frozen_pydantic_error(e: Exception) -> bool:
    """Parses an error to determine if it is a Pydantic error indicating that the instance
    is immutable. We use this to attach a more helpful error message.
    """
    return "Instance is frozen" in str(  # Pydantic 2.x error
        e
    ) or "is immutable and does not support item assignment" in str(  # Pydantic 1.x error
        e
    )


class MakeConfigCacheable(BaseModel):
    """This class centralizes and implements all the chicanery we need in order
    to support caching decorators. If we decide this is a bad idea we can remove it
    all in one go.
    """

    # Pydantic config for this class
    # Cannot use kwargs for base class as this is not support for pydnatic<1.8
    class Config:
        # Various pydantic model config (https://docs.pydantic.dev/usage/model_config/)
        # Necessary to allow for caching decorators
        arbitrary_types_allowed = True
        # Avoid pydantic reading a cached property class as part of the schema
        if USING_PYDANTIC_2:
            ignored_types = (cached_property,)
        else:
            keep_untouched = (cached_property,)
        # Ensure the class is serializable, for caching purposes
        frozen = True

    def __setattr__(self, name: str, value: Any):
        from .resource import ConfigurableResourceFactory

        # This is a hack to allow us to set attributes on the class that are not part of the
        # config schema. Pydantic will normally raise an error if you try to set an attribute
        # that is not part of the schema.

        if self._is_field_internal(name):
            object.__setattr__(self, name, value)
            return

        try:
            return super().__setattr__(name, value)
        except (TypeError, ValueError) as e:
            clsname = self.__class__.__name__
            if _is_frozen_pydantic_error(e):
                if isinstance(self, ConfigurableResourceFactory):
                    raise DagsterInvalidInvocationError(
                        f"'{clsname}' is a Pythonic resource and does not support item assignment,"
                        " as it inherits from 'pydantic.BaseModel' with frozen=True. If trying to"
                        " maintain state on this resource, consider building a separate, stateful"
                        " client class, and provide a method on the resource to construct and"
                        " return the stateful client."
                    ) from e
                else:
                    raise DagsterInvalidInvocationError(
                        f"'{clsname}' is a Pythonic config class and does not support item"
                        " assignment, as it inherits from 'pydantic.BaseModel' with frozen=True."
                    ) from e
            elif "object has no field" in str(e):
                field_name = check.not_none(
                    re.search(r"object has no field \"(.*)\"", str(e))
                ).group(1)
                if isinstance(self, ConfigurableResourceFactory):
                    raise DagsterInvalidInvocationError(
                        f"'{clsname}' is a Pythonic resource and does not support manipulating"
                        f" undeclared attribute '{field_name}' as it inherits from"
                        " 'pydantic.BaseModel' without extra=\"allow\". If trying to maintain"
                        " state on this resource, consider building a separate, stateful client"
                        " class, and provide a method on the resource to construct and return the"
                        " stateful client."
                    ) from e
                else:
                    raise DagsterInvalidInvocationError(
                        f"'{clsname}' is a Pythonic config class and does not support manipulating"
                        f" undeclared attribute '{field_name}' as it inherits from"
                        " 'pydantic.BaseModel' without extra=\"allow\"."
                    ) from e
            else:
                raise

    def _is_field_internal(self, name: str) -> bool:
        return name.endswith(INTERNAL_MARKER)


T = TypeVar("T")


def ensure_env_vars_set_post_init(set_value: T, input_value: Any) -> T:
    """Pydantic 2.x utility. Ensures that Pydantic field values are set to the appropriate
    EnvVar or IntEnvVar objects post-model-instantiation, since Pydantic 2.x will cast
    EnvVar or IntEnvVar values to raw strings or ints as part of the model instantiation process.
    """
    if isinstance(set_value, dict) and isinstance(input_value, dict):
        for key, value in input_value.items():
            if isinstance(value, (EnvVar, IntEnvVar)):
                set_value[key] = value
            elif isinstance(value, (dict, list)):
                set_value[key] = ensure_env_vars_set_post_init(set_value[key], value)
    if isinstance(set_value, List) and isinstance(input_value, List):
        for i in range(len(set_value)):
            value = input_value[i]
            if isinstance(value, (EnvVar, IntEnvVar)):
                set_value[i] = value
            elif isinstance(value, (dict, list)):
                set_value[i] = ensure_env_vars_set_post_init(set_value[i], value)

    return set_value


class Config(MakeConfigCacheable, metaclass=BaseConfigMeta):
    """Base class for Dagster configuration models, used to specify config schema for
    ops and assets. Subclasses :py:class:`pydantic.BaseModel`.

    Example definition:

    .. code-block:: python

        from pydantic import Field

        class MyAssetConfig(Config):
            my_str: str = "my_default_string"
            my_int_list: List[int]
            my_bool_with_metadata: bool = Field(default=False, description="A bool field")


    Example usage:

    .. code-block:: python

        @asset
        def asset_with_config(config: MyAssetConfig):
            assert config.my_str == "my_default_string"
            assert config.my_int_list == [1, 2, 3]
            assert config.my_bool_with_metadata == False

        asset_with_config(MyAssetConfig(my_int_list=[1, 2, 3], my_bool_with_metadata=True))

    """

    def __init__(self, **config_dict) -> None:
        """This constructor is overridden to handle any remapping of raw config dicts to
        the appropriate config classes. For example, discriminated unions are represented
        in Dagster config as dicts with a single key, which is the discriminator value.
        """
        modified_data = {}
        for key, value in config_dict.items():
            field = model_fields(self).get(key)

            # This is useful in Pydantic 2.x when reconstructing a config object from a dict
            # e.g. when instantiating a resource at runtime from its config dict
            # In Pydantic 1.x, this is a no-op, since a non-required field without a
            # value provided will default to None (required & optional are the same in 1.x)
            if field and not field.is_required() and value is None:
                continue

            if field and field.discriminator:
                nested_dict = value

                discriminator_key = check.not_none(field.discriminator)
                if isinstance(value, Config):
                    nested_dict = _discriminated_union_config_dict_to_selector_config_dict(
                        discriminator_key,
                        value._get_non_none_public_field_values(),  # noqa: SLF001
                    )

                nested_items = list(check.is_dict(nested_dict).items())
                check.invariant(
                    len(nested_items) == 1,
                    "Discriminated union must have exactly one key",
                )
                discriminated_value, nested_values = nested_items[0]

                modified_data[key] = {
                    **nested_values,
                    discriminator_key: discriminated_value,
                }
            else:
                modified_data[key] = value

        for key, field in model_fields(self).items():
            if field.is_required() and key not in modified_data:
                modified_data[key] = None

        super().__init__(**modified_data)
        if USING_PYDANTIC_2:
            self.__dict__ = ensure_env_vars_set_post_init(self.__dict__, modified_data)

    def _convert_to_config_dictionary(self) -> Mapping[str, Any]:
        """Converts this Config object to a Dagster config dictionary, in the same format as the dictionary
        accepted as run config or as YAML in the launchpad.

        Inner fields are recursively converted to dictionaries, meaning nested config objects
        or EnvVars will be converted to the appropriate dictionary representation.
        """
        public_fields = self._get_non_none_public_field_values()
        return {
            k: _config_value_to_dict_representation(model_fields(self).get(k), v)
            for k, v in public_fields.items()
        }

    def _get_non_none_public_field_values(self) -> Mapping[str, Any]:
        """Returns a dictionary representation of this config object,
        ignoring any private fields, and any optional fields that are None.

        Inner fields are returned as-is in the dictionary,
        meaning any nested config objects will be returned as config objects, not dictionaries.
        """
        output = {}
        for key, value in self.__dict__.items():
            if self._is_field_internal(key):
                continue
            field = model_fields(self).get(key)

            if field:
                resolved_field_name = field.alias or key
                output[resolved_field_name] = value
            else:
                output[key] = value
        return output

    @classmethod
    def to_config_schema(cls) -> DefinitionConfigSchema:
        """Converts the config structure represented by this class into a DefinitionConfigSchema."""
        return DefinitionConfigSchema(infer_schema_from_config_class(cls))

    @classmethod
    def to_fields_dict(cls) -> Dict[str, DagsterField]:
        """Converts the config structure represented by this class into a dictionary of dagster.Fields.
        This is useful when interacting with legacy code that expects a dictionary of fields but you
        want the source of truth to be a config class.
        """
        return cast(Shape, cls.to_config_schema().as_field().config_type).fields


def _discriminated_union_config_dict_to_selector_config_dict(
    discriminator_key: str, config_dict: Mapping[str, Any]
):
    """Remaps a config dictionary which is a member of a discriminated union to
    the appropriate structure for a Dagster config selector.

    A discriminated union with key "my_key" and value "my_value" will be represented
    as {"my_key": "my_value", "my_field": "my_field_value"}. When converted to a selector,
    this should be represented as {"my_value": {"my_field": "my_field_value"}}.
    """
    updated_dict = dict(config_dict)
    discriminator_value = updated_dict.pop(discriminator_key)
    wrapped_dict = {discriminator_value: updated_dict}
    return wrapped_dict


def _config_value_to_dict_representation(field: Optional[ModelFieldCompat], value: Any):
    """Converts a config value to a dictionary representation. If a field is provided, it will be used
    to determine the appropriate dictionary representation in the case of discriminated unions.
    """
    from dagster._config.field_utils import EnvVar, IntEnvVar

    if isinstance(value, dict):
        return {k: _config_value_to_dict_representation(None, v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_config_value_to_dict_representation(None, v) for v in value]
    elif isinstance(value, EnvVar):
        return {"env": value.env_var_name}
    elif isinstance(value, IntEnvVar):
        return {"env": value.name}
    if isinstance(value, Config):
        if field and field.discriminator:
            return {
                k: v
                for k, v in _discriminated_union_config_dict_to_selector_config_dict(
                    field.discriminator,
                    value._convert_to_config_dictionary(),  # noqa: SLF001
                ).items()
            }
        else:
            return {k: v for k, v in value._convert_to_config_dictionary().items()}  # noqa: SLF001
    elif isinstance(value, Enum):
        return value.name

    return value


class PermissiveConfig(Config):
    """Subclass of :py:class:`Config` that allows arbitrary extra fields. This is useful for
    config classes which may have open-ended inputs.

    Example definition:

    .. code-block:: python

        class MyPermissiveOpConfig(PermissiveConfig):
            my_explicit_parameter: bool
            my_other_explicit_parameter: str


    Example usage:

    .. code-block:: python

        @op
        def op_with_config(config: MyPermissiveOpConfig):
            assert config.my_explicit_parameter == True
            assert config.my_other_explicit_parameter == "foo"
            assert config.dict().get("my_implicit_parameter") == "bar"

        op_with_config(
            MyPermissiveOpConfig(
                my_explicit_parameter=True,
                my_other_explicit_parameter="foo",
                my_implicit_parameter="bar"
            )
        )

    """

    # Pydantic config for this class
    # Cannot use kwargs for base class as this is not support for pydantic<1.8
    class Config:
        extra = "allow"


def infer_schema_from_config_class(
    model_cls: Type["Config"],
    description: Optional[str] = None,
    fields_to_omit: Optional[Set[str]] = None,
) -> DagsterField:
    from .config import Config
    from .resource import ConfigurableResourceFactory, _is_annotated_as_resource_type

    """Parses a structured config class and returns a corresponding Dagster config Field."""
    fields_to_omit = fields_to_omit or set()

    check.param_invariant(
        safe_is_subclass(model_cls, Config),
        "Config type annotation must inherit from dagster.Config",
    )

    fields: Dict[str, DagsterField] = {}
    for key, pydantic_field_info in model_fields(model_cls).items():
        if _is_annotated_as_resource_type(
            pydantic_field_info.annotation, pydantic_field_info.metadata
        ):
            continue

        resolved_field_name = pydantic_field_info.alias if pydantic_field_info.alias else key
        if key not in fields_to_omit:
            if isinstance(pydantic_field_info.default, DagsterField):
                raise DagsterInvalidDefinitionError(
                    "Using 'dagster.Field' is not supported within a Pythonic config or resource"
                    " definition. 'dagster.Field' should only be used in legacy Dagster config"
                    " schemas. Did you mean to use 'pydantic.Field' instead?"
                )

            try:
                fields[resolved_field_name] = _convert_pydantic_field(pydantic_field_info)
            except DagsterInvalidConfigDefinitionError as e:
                raise DagsterInvalidPythonicConfigDefinitionError(
                    config_class=model_cls,
                    field_name=key,
                    invalid_type=e.current_value,
                    is_resource=model_cls is not None
                    and safe_is_subclass(model_cls, ConfigurableResourceFactory),
                )

    shape_cls = Permissive if model_config(model_cls).get("extra") == "allow" else Shape

    docstring = model_cls.__doc__.strip() if model_cls.__doc__ else None

    return DagsterField(config=shape_cls(fields), description=description or docstring)
