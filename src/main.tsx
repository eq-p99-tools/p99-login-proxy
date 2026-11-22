import React from "react";
import ReactDOM from "react-dom/client";

import App from "./app/App";
import { ModalApp, isModalWindow } from "./features/modals";
import "./styles/tokens.css";
import "./styles/app.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>{isModalWindow() ? <ModalApp /> : <App />}</React.StrictMode>,
);
