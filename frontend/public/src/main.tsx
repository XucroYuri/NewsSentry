import React from "react"
import ReactDOM from "react-dom/client"

import App from "@/App"
import "@/index.css"

async function start() {
  if (import.meta.env.MODE === "redesign-preview") {
    const { installLocalPreview } = await import("@/preview/local-preview")
    installLocalPreview()
  }
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
}

void start()
