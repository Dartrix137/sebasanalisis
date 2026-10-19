import { expect, test } from "@playwright/test";

import {
  cardBrand,
  cardFieldErrors,
  cardNumberValid,
  formatCardNumber,
  formatCvc,
  formatExpiry,
  formatHolder,
  formatPhone,
  nequiPhoneValid,
  parseExpiry,
} from "../lib/card-input";

/**
 * Formato y validación del formulario de tarjeta y Nequi (§3.16). Funciones
 * puras: se prueban aquí, sin navegador, como `monitoring.spec.ts`.
 */

const HOY = new Date(2026, 9, 19); // 19 de octubre de 2026

test("el número: solo dígitos, en grupos, hasta el largo de su marca", () => {
  expect(formatCardNumber("4242abc4242-4242 4242")).toBe("4242 4242 4242 4242");
  expect(formatCardNumber("$%&")).toBe("");
  // Visa admite hasta 19; Mastercard, 16; American Express, 15 en grupos 4-6-5.
  expect(formatCardNumber("4".repeat(25))).toBe("4444 4444 4444 4444 444");
  expect(formatCardNumber("5555555555554444999")).toBe("5555 5555 5555 4444");
  expect(formatCardNumber("378282246310005999")).toBe("3782 822463 10005");
});

test("la marca sale de los primeros dígitos", () => {
  expect(cardBrand("4242")).toBe("visa");
  expect(cardBrand("5105")).toBe("mastercard");
  expect(cardBrand("2221 00")).toBe("mastercard");
  expect(cardBrand("3782")).toBe("amex");
  expect(cardBrand("3056")).toBe("diners");
  expect(cardBrand("9999")).toBeNull();
});

test("el número se valida con Luhn y con el largo de su marca", () => {
  expect(cardNumberValid("4242 4242 4242 4242")).toBe(true);
  expect(cardNumberValid("4111 1111 1111 1111")).toBe(true);
  expect(cardNumberValid("4242 4242 4242 4241")).toBe(false);
  expect(cardNumberValid("3782 822463 10005")).toBe(true);
  // Pasa Luhn pero un Mastercard no tiene 15 dígitos.
  expect(cardNumberValid("510510510510518")).toBe(false);
  expect(cardNumberValid("")).toBe(false);
});

test("el vencimiento: MM/AA, sin meses imposibles ni letras", () => {
  expect(formatExpiry("0")).toBe("0");
  expect(formatExpiry("08")).toBe("08");
  expect(formatExpiry("083")).toBe("08/3");
  expect(formatExpiry("0830")).toBe("08/30");
  // Un primer dígito mayor que 1 ya es el mes.
  expect(formatExpiry("4")).toBe("04");
  expect(formatExpiry("99")).toBe("09/9");
  // Ni 00 ni 13: el segundo dígito no se deja escribir.
  expect(formatExpiry("00")).toBe("0");
  expect(formatExpiry("13")).toBe("1");
  expect(formatExpiry("1e")).toBe("1");
  // Una barra después de un solo dígito: ese dígito es el mes.
  expect(formatExpiry("1/")).toBe("01");
  // Borrar el año no deja la barra trabada.
  expect(formatExpiry("08/")).toBe("08");
  // Lo que llena el autocompletado.
  expect(formatExpiry("08/2030")).toBe("08/30");
  expect(formatExpiry("082030")).toBe("08/30");
  expect(formatExpiry("8/30")).toBe("08/30");
  expect(formatExpiry("08/305")).toBe("08/30");
  expect(parseExpiry("08/30")).toEqual({ expMonth: "08", expYear: "30" });
});

test("el CVC: 3 dígitos, o 4 en American Express", () => {
  expect(formatCvc("9a8x7 6", "visa")).toBe("987");
  expect(formatCvc("12345", "amex")).toBe("1234");
  expect(formatCvc("12345", null)).toBe("1234");
});

test("el titular: letras con tildes, espacios, apóstrofos, puntos y guiones", () => {
  expect(formatHolder("José 4 Pérez!")).toBe("José Pérez");
  expect(formatHolder("Ana-María O'Neil Jr.")).toBe("Ana-María O'Neil Jr.");
});

test("cada campo dice qué corregir", () => {
  const bien = { number: "4242 4242 4242 4242", expiry: "08/30", cvc: "123", holder: "José Pérez" };
  expect(cardFieldErrors(bien, HOY)).toEqual({});
  expect(cardFieldErrors({ number: "", expiry: "", cvc: "", holder: "" }, HOY)).toEqual({
    number: "Escribe el número de la tarjeta.",
    expiry: "Escribe el mes y el año de vencimiento.",
    cvc: "El código de seguridad tiene 3 o 4 dígitos.",
    holder: "Escribe el nombre del titular como aparece en la tarjeta.",
  });
  expect(cardFieldErrors({ ...bien, number: "4242 4242 4242 4241" }, HOY).number).toBe(
    "El número de la tarjeta no es válido.",
  );
  expect(cardFieldErrors({ ...bien, expiry: "08/2" }, HOY).expiry).toBe(
    "Escribe el vencimiento como MM/AA.",
  );
  // Vale hasta el último día de su mes.
  expect(cardFieldErrors({ ...bien, expiry: "10/26" }, HOY)).toEqual({});
  expect(cardFieldErrors({ ...bien, expiry: "09/26" }, HOY).expiry).toBe("Esta tarjeta ya venció.");
  expect(cardFieldErrors({ ...bien, cvc: "1234" }, HOY).cvc).toBe(
    "El código de seguridad tiene 3 dígitos.",
  );
  expect(
    cardFieldErrors({ ...bien, number: "3782 822463 10005", cvc: "123" }, HOY).cvc,
  ).toBe("El código de seguridad tiene 4 dígitos.");
});

test("el celular de Nequi: diez dígitos que empiezan por 3", () => {
  expect(formatPhone("399-111 1111 22")).toBe("399 111 1111");
  expect(nequiPhoneValid("3991111111")).toBe(true);
  expect(nequiPhoneValid("2991111111")).toBe(false);
  expect(nequiPhoneValid("399111111")).toBe(false);
});
