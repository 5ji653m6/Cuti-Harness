/** Read an index already checked by the caller, failing explicitly if its range is invalid. */
export function arrayItem<T>(values: ArrayLike<T>, index: number): T {
  const value = values[index]
  if (value === undefined) throw new RangeError(`Array index ${index} is out of range`)
  return value
}
