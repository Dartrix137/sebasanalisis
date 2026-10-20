import type { Metadata } from "next";

import { AuthForm } from "@/components/AuthForm";

export const metadata: Metadata = {
  title: "Iniciar sesión",
  description:
    "Entra a tu cuenta de Sebasanálisis para registrar los números de tu mesa y ver la recomendación estadística de cada giro.",
};

export default function LoginPage() {
  return <AuthForm mode="login" />;
}
