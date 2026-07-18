interface ErrorAlertProps {
  message: string;
}

export function ErrorAlert({ message }: ErrorAlertProps) {
  return (
    <p className="error-alert" role="alert">
      {message}
    </p>
  );
}
