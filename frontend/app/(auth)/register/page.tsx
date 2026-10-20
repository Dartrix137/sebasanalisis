import type { Metadata } from "next";

import { AuthForm } from "@/components/AuthForm";

export const metadata: Metadata = {
  title: "Crear cuenta",
  description:
    "Crea tu cuenta en Sebasanálisis. El acceso a la mesa se activa con una suscripción.",
};

export default function RegisterPage() {
  return <AuthForm mode="register" />;
}
