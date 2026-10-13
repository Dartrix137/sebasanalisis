import { Suspense } from "react";

import { PaymentResult } from "./PaymentResult";

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
