/**
 * Pide al procesador de pagos el token de un medio de pago (§3.4 de la Fase 4).
 *
 * El cliente escribe su tarjeta, o aprueba su Nequi, en la ventana de Wompi. A
 * esta página solo vuelve un token y su tipo: los datos de la tarjeta nunca
 * pasan por nuestro código ni por nuestro servidor.
 *
 * El widget se abre en modo tokenización. La documentación de Wompi lo menciona
 * ("Fuentes de pago", consultada el 2026-10-13) sin detallar la forma del
 * resultado; se leyó del propio `widget.js` ese día: al terminar llama al
 * callback con `{ payment_source: { token, type } }`. Si el cliente cierra la
 * ventana, el callback no se llama. Comprobado contra el sandbox ese mismo día.
 *
 * El widget cifra la tarjeta en el navegador y eso exige un contexto seguro:
 * https o `localhost`. Desde otro origen http responde "Tu tarjeta no pudo ser
 * verificada (error desconocido)".
 */

import type { PaymentSourceKind } from "./types/billing";

const WIDGET_URL = "https://checkout.wompi.co/widget.js";

export interface TokenizedSource {
  token: string;
  type: PaymentSourceKind;
}

interface WidgetResult {
  payment_source?: { token?: unknown; type?: unknown };
}

interface WidgetInstance {
  open: (callback: (result: WidgetResult) => void) => void;
}

declare global {
  interface Window {
    WidgetCheckout?: new (config: { publicKey: string; widgetOperation: "tokenize" }) => WidgetInstance;
  }
}

let loading: Promise<void> | null = null;

function loadWidget(): Promise<void> {
  if (window.WidgetCheckout) return Promise.resolve();
  if (!loading) {
    loading = new Promise<void>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = WIDGET_URL;
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => {
        loading = null;
        script.remove();
        reject(new Error("No se pudo cargar el formulario del procesador de pagos"));
      };
      document.head.appendChild(script);
    });
  }
  return loading;
}

/**
 * Abre la ventana de Wompi y llama a `onToken` cuando el cliente termina. Si la
 * cierra sin terminar no pasa nada: puede volver a abrirla.
 *
 * Lanza si el widget no se pudo cargar. `onInvalid` se llama si Wompi devuelve
 * un medio que no se puede guardar para la renovación automática.
 */
export async function openTokenizer(
  publicKey: string,
  onToken: (source: TokenizedSource) => void,
  onInvalid: () => void,
): Promise<void> {
  await loadWidget();
  if (!window.WidgetCheckout) {
    throw new Error("No se pudo cargar el formulario del procesador de pagos");
  }
  const widget = new window.WidgetCheckout({ publicKey, widgetOperation: "tokenize" });
  widget.open((result) => {
    const source = result.payment_source;
    const token = source?.token;
    const type = source?.type;
    if (typeof token === "string" && token && (type === "CARD" || type === "NEQUI")) {
      onToken({ token, type });
    } else {
      onInvalid();
    }
  });
}
