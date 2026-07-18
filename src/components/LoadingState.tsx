interface LoadingStateProps {
  message?: string;
}

export function LoadingState({ message = "Loading…" }: LoadingStateProps) {
  return <p className="loading-state" aria-live="polite">{message}</p>;
}
