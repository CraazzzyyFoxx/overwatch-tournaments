/**
 * The organizer page's closing banner hands the name typed into it to the
 * create form in the hero, which takes it as if typed there and brings itself
 * into view. One page, one form: a module-level listener set is all the
 * channel needs.
 */
type Listener = (name: string) => void;

const listeners = new Set<Listener>();

export function handOffName(name: string) {
  for (const listener of listeners) listener(name);
}

/** Subscribes the form; returns the unsubscribe for an effect's cleanup. */
export function onNameHandOff(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
