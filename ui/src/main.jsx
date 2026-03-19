import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import SegnogUI from "./SegnogUI.jsx";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <SegnogUI />
  </StrictMode>
);
