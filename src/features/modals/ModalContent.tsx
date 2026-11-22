import type { ModalBody, ModalLevel } from "../../ipc/schemas";

const LEVEL_ICON: Record<ModalLevel, string> = { info: "i", warning: "!", error: "×" };
const LEVEL_LABEL: Record<ModalLevel, string> = { info: "Info", warning: "Warning", error: "Error" };

export function ModalLevelIcon({ level }: { level: ModalLevel }) {
  return (
    <span className={`modal-level-icon modal-level-${level}`} role="img" aria-label={LEVEL_LABEL[level]}>
      {LEVEL_ICON[level]}
    </span>
  );
}

/**
 * Body of any popup, shared by the in-app dialog and the topmost window.
 * Everything is rendered as text, never markup.
 */
export function ModalContent({ body }: { body: ModalBody }) {
  if (body.kind === "text") {
    return <p className="modal-message-pre">{body.message}</p>;
  }
  return (
    <div className="login-notes">
      {body.username.toLowerCase() !== body.account.toLowerCase() ? (
        <p className="login-notes-muted">Logged in as {body.username}</p>
      ) : null}
      {body.account_notes ? <p className="login-notes-text">{body.account_notes}</p> : null}
      {body.characters.length > 0 ? (
        <ul className="login-notes-characters">
          {body.characters.map((c) => (
            <li key={c.name} className={c.typed ? "login-notes-typed" : undefined}>
              <strong>{c.name}</strong>
              {c.typed ? <span className="login-notes-muted"> (the name you logged in with)</span> : null}
              <p className="login-notes-text">{c.notes}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
