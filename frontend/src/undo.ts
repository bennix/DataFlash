import { useCallback, useRef, useState } from "react";

const MAX = 40;

export function useUndoable<T>(initial: T) {
  const [present, setPresent] = useState(initial);
  const past = useRef<T[]>([]);
  const future = useRef<T[]>([]);

  const commit = useCallback((next: T | ((prev: T) => T)) => {
    setPresent((prev) => {
      const value = typeof next === "function" ? (next as (p: T) => T)(prev) : next;
      past.current = [...past.current.slice(-(MAX - 1)), prev];
      future.current = [];
      return value;
    });
  }, []);

  const replace = useCallback((next: T) => {
    setPresent(next);
    past.current = [];
    future.current = [];
  }, []);

  const undo = useCallback(() => {
    setPresent((prev) => {
      if (!past.current.length) return prev;
      const prior = past.current[past.current.length - 1];
      past.current = past.current.slice(0, -1);
      future.current = [prev, ...future.current].slice(0, MAX);
      return prior;
    });
  }, []);

  const redo = useCallback(() => {
    setPresent((prev) => {
      if (!future.current.length) return prev;
      const next = future.current[0];
      future.current = future.current.slice(1);
      past.current = [...past.current, prev].slice(-MAX);
      return next;
    });
  }, []);

  return { present, commit, replace, undo, redo, canUndo: () => past.current.length > 0 };
}
