import { Suspense } from "react";

import { privateMetadata } from "@/lib/site";

import { PaymentResult } from "./PaymentResult";

export const metadata = privateMetadata("Tu pago");

export default async function PaymentResultPage({
  params,
}: {
  params: Promise<{ paymentId: string }>;
}) {
  const { paymentId } = await params;
  return (
    // useSearchParams (el `?id=` que agrega la pasarela) necesita un límite de Suspense.
    <Suspense fallback={null}>
      <PaymentResult paymentId={paymentId} />
    </Suspense>
  );
}
