/**
 * The type of one query-key segment.
 *
 * Deliberately wide. A segment is an identity marker, not a typed value: the
 * same id arrives as `number` from a resolved route, `null` from an unset scope
 * chip and `undefined` from a workspace that has not loaded yet, and those three
 * are three different cache entries on purpose. Narrowing per factory would buy
 * no safety a mistyped key does not already have, and would force a cast at
 * every call site that legitimately holds a nullable id.
 *
 * Structured segments -- a filter object, a request payload -- are typed
 * `unknown` by the factory that takes them.
 */
export type KeyPart = string | number | boolean | null | undefined;
