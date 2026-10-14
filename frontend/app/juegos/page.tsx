import { redirect } from "next/navigation";

/** El menú de juegos vive en el inicio. */
export default function JuegosPage() {
  redirect("/dashboard");
}
