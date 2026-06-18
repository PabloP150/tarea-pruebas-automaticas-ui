import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import App from "./App.tsx";
import CreateTicket from "./pages/CreateTicket.tsx";
import Dashboard from "./pages/Dashboard.tsx";
import TicketDetail from "./pages/TicketDetail.tsx";
import { NowProvider } from "./providers/NowProvider.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <NowProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<App />}>
            <Route index element={<Navigate to="/nuevo" replace />} />
            <Route path="nuevo" element={<CreateTicket />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="ticket/:id" element={<TicketDetail />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </NowProvider>
  </StrictMode>
);
