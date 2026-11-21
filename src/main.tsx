import React from "react";
import ReactDOM from "react-dom/client";

import App from "./app/App";
import { LoginNotesApp, isLoginNotesWindow } from "./features/loginNotes";
import "./styles/tokens.css";
import "./styles/app.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>{isLoginNotesWindow() ? <LoginNotesApp /> : <App />}</React.StrictMode>,
);
