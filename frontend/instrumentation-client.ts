// Next carga este archivo en el navegador antes de hidratar la aplicación.
import * as Sentry from "@sentry/nextjs";

import { monitoringOptions } from "@/lib/monitoring";

Sentry.init(monitoringOptions);

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
