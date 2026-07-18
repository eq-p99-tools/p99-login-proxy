import { Button } from "./Button";
import { ModalDialog } from "./ModalDialog";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  onConfirm,
  onCancel,
  busy = false,
}: ConfirmDialogProps) {
  return (
    <ModalDialog
      title={title}
      open={open}
      onClose={onCancel}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} busy={busy}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p>{message}</p>
    </ModalDialog>
  );
}
