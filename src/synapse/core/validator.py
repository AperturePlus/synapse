"""IR validation module.

This module provides validation for IR structures, ensuring all ID references
are valid and the data is consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from synapse.core.models import IR


class ValidationErrorType(str, Enum):
    """Types of validation errors."""

    DANGLING_MODULE_REF = "dangling_module_reference"
    DANGLING_TYPE_REF = "dangling_type_reference"
    DANGLING_CALLABLE_REF = "dangling_callable_reference"
    INVALID_SELF_REF = "invalid_self_reference"


@dataclass
class ValidationError:
    """A single validation error."""

    error_type: ValidationErrorType
    entity_id: str
    field_name: str
    invalid_ref: str
    message: str


@dataclass
class ValidationResult:
    """Result of IR validation."""

    is_valid: bool
    errors: list[ValidationError] = field(default_factory=list)

    def add_error(
        self,
        error_type: ValidationErrorType,
        entity_id: str,
        field_name: str,
        invalid_ref: str,
        message: str,
    ) -> None:
        """Add a validation error."""
        self.errors.append(
            ValidationError(
                error_type=error_type,
                entity_id=entity_id,
                field_name=field_name,
                invalid_ref=invalid_ref,
                message=message,
            )
        )
        self.is_valid = False


def validate_ir(ir: IR) -> ValidationResult:
    """Validate an IR structure for reference integrity.

    Checks that all ID references in the IR point to existing entities.

    Args:
        ir: The IR structure to validate.

    Returns:
        ValidationResult containing validation status and any errors found.
    """
    result = ValidationResult(is_valid=True)

    # Collect all valid IDs
    valid_module_ids = set(ir.modules.keys())
    valid_type_ids = set(ir.types.keys())
    valid_callable_ids = set(ir.callables.keys())

    # Validate Module references
    for module_id, module in ir.modules.items():
        # Check sub_modules references
        for sub_id in module.sub_modules:
            if sub_id not in valid_module_ids:
                result.add_error(
                    error_type=ValidationErrorType.DANGLING_MODULE_REF,
                    entity_id=module_id,
                    field_name="sub_modules",
                    invalid_ref=sub_id,
                    message=f"Module '{module_id}' references non-existent sub-module '{sub_id}'",
                )
            elif sub_id == module_id:
                result.add_error(
                    error_type=ValidationErrorType.INVALID_SELF_REF,
                    entity_id=module_id,
                    field_name="sub_modules",
                    invalid_ref=sub_id,
                    message=f"Module '{module_id}' cannot reference itself as sub-module",
                )

        # Check declared_types references
        for type_id in module.declared_types:
            if type_id not in valid_type_ids:
                result.add_error(
                    error_type=ValidationErrorType.DANGLING_TYPE_REF,
                    entity_id=module_id,
                    field_name="declared_types",
                    invalid_ref=type_id,
                    message=f"Module '{module_id}' references non-existent type '{type_id}'",
                )

    # Validate Type references
    for type_id, type_def in ir.types.items():
        # Check extends references
        for ext_id in type_def.extends:
            if ext_id not in valid_type_ids:
                result.add_error(
                    error_type=ValidationErrorType.DANGLING_TYPE_REF,
                    entity_id=type_id,
                    field_name="extends",
                    invalid_ref=ext_id,
                    message=f"Type '{type_id}' extends non-existent type '{ext_id}'",
                )

        # Check implements references
        for impl_id in type_def.implements:
            if impl_id not in valid_type_ids:
                result.add_error(
                    error_type=ValidationErrorType.DANGLING_TYPE_REF,
                    entity_id=type_id,
                    field_name="implements",
                    invalid_ref=impl_id,
                    message=f"Type '{type_id}' implements non-existent type '{impl_id}'",
                )

        # Check embeds references
        for embed_id in type_def.embeds:
            if embed_id not in valid_type_ids:
                result.add_error(
                    error_type=ValidationErrorType.DANGLING_TYPE_REF,
                    entity_id=type_id,
                    field_name="embeds",
                    invalid_ref=embed_id,
                    message=f"Type '{type_id}' embeds non-existent type '{embed_id}'",
                )

        # Check callables references
        for call_id in type_def.callables:
            if call_id not in valid_callable_ids:
                result.add_error(
                    error_type=ValidationErrorType.DANGLING_CALLABLE_REF,
                    entity_id=type_id,
                    field_name="callables",
                    invalid_ref=call_id,
                    message=f"Type '{type_id}' references non-existent callable '{call_id}'",
                )

    return _validate_callables(ir, result, valid_type_ids, valid_callable_ids)


def _validate_callables(
    ir: IR,
    result: ValidationResult,
    valid_type_ids: set[str],
    valid_callable_ids: set[str],
) -> ValidationResult:
    """Validate Callable references in the IR.

    Args:
        ir: The IR structure to validate.
        result: The validation result to update.
        valid_type_ids: Set of valid type IDs.
        valid_callable_ids: Set of valid callable IDs.

    Returns:
        Updated ValidationResult.
    """
    for call_id, callable_def in ir.callables.items():
        # Check return_type reference
        if callable_def.return_type is not None:
            if callable_def.return_type not in valid_type_ids:
                result.add_error(
                    error_type=ValidationErrorType.DANGLING_TYPE_REF,
                    entity_id=call_id,
                    field_name="return_type",
                    invalid_ref=callable_def.return_type,
                    message=f"Callable '{call_id}' has non-existent return type "
                    f"'{callable_def.return_type}'",
                )

        # Check calls references
        for target_id in callable_def.calls:
            if target_id not in valid_callable_ids:
                result.add_error(
                    error_type=ValidationErrorType.DANGLING_CALLABLE_REF,
                    entity_id=call_id,
                    field_name="calls",
                    invalid_ref=target_id,
                    message=f"Callable '{call_id}' calls non-existent callable '{target_id}'",
                )

        # Check overrides reference
        if callable_def.overrides is not None:
            if callable_def.overrides not in valid_callable_ids:
                result.add_error(
                    error_type=ValidationErrorType.DANGLING_CALLABLE_REF,
                    entity_id=call_id,
                    field_name="overrides",
                    invalid_ref=callable_def.overrides,
                    message=f"Callable '{call_id}' overrides non-existent callable "
                    f"'{callable_def.overrides}'",
                )

    return result
