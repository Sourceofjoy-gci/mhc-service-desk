const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+$/;

export function hasContent(value: string) {
  return value.trim().length > 0;
}

export function isOptionalEmailValid(value: string) {
  const normalized = value.trim();
  return normalized.length === 0 || EMAIL_PATTERN.test(normalized);
}

export function getFirstInvalidFieldId(
  fields: ReadonlyArray<{ id: string; valid: boolean }>,
) {
  return fields.find((field) => !field.valid)?.id ?? null;
}
