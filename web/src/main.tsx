import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./styles/index.css";
import { initTheme } from "./hooks/useTheme";
import App from "./App";

initTheme(); // before the first paint, so a saved light theme doesn't flash dark

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
