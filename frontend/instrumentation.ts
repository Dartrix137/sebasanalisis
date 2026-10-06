// Next llama a `register` una vez al arrancar el servidor.
import * as Sentry from "@sentry/nextjs";

import { monitoringOptions } from "@/lib/monitoring";

export function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    Sentry.init(monitoringOptions);
  }
}

export const onRequestError = Sentry.captureRequestError;
