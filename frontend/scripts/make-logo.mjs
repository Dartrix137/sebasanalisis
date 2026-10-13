// Saca el logo del fondo negro y genera los archivos que usa la pagina.
// Se corre desde frontend/:  node scripts/make-logo.mjs ../docs/design/logo-original.webp
//
// El original es dorado sobre negro, sin transparencia. El negro se vuelve
// transparente segun el brillo de cada pixel: asi el borde suavizado del
// dorado queda semitransparente en vez de con un halo negro.
import fs from "node:fs";
import path from "node:path";

import sharp from "sharp";

const SRC = process.argv[2];
const LOW = 28; // por debajo de este brillo, transparente (ruido de compresion del negro)
const HIGH = 120; // por encima, opaco

async function main() {
  const { data, info } = await sharp(SRC).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  const { width, height } = info;
  const rgba = Buffer.alloc(width * height * 4);
  const rowHasInk = new Array(height).fill(false);
  for (let i = 0, j = 0; i < data.length; i += 3, j += 4) {
    const r = data[i], g = data[i + 1], b = data[i + 2];
    const max = Math.max(r, g, b);
    let a = (max - LOW) / (HIGH - LOW);
    a = a < 0 ? 0 : a > 1 ? 1 : a;
    if (a > 0) {
      // Deshace la mezcla con el negro para recuperar el dorado del borde.
      const k = a < 1 ? Math.min(1 / a, HIGH / Math.max(max, 1)) : 1;
      rgba[j] = Math.min(255, Math.round(r * k));
      rgba[j + 1] = Math.min(255, Math.round(g * k));
      rgba[j + 2] = Math.min(255, Math.round(b * k));
      rgba[j + 3] = Math.round(a * 255);
      if (a > 0.5) rowHasInk[Math.floor(j / 4 / width)] = true;
    }
  }

  // Bloques de filas con tinta, separados por franjas vacias: el primero es el
  // hexagono; los demas, el texto.
  const blocks = [];
  let start = -1, gap = 0;
  for (let y = 0; y < height; y++) {
    if (rowHasInk[y]) {
      if (start < 0) start = y;
      gap = 0;
    } else if (start >= 0 && ++gap >= 12) {
      blocks.push([start, y - gap]);
      start = -1;
      gap = 0;
    }
  }
  if (start >= 0) blocks.push([start, height - 1]);
  console.log("bloques de filas:", JSON.stringify(blocks));

  const colRange = (y0, y1) => {
    let x0 = width, x1 = -1;
    for (let y = y0; y <= y1; y++) {
      for (let x = 0; x < width; x++) {
        if (rgba[(y * width + x) * 4 + 3] > 128) {
          if (x < x0) x0 = x;
          if (x > x1) x1 = x;
        }
      }
    }
    return [x0, x1];
  };
  const region = (y0, y1, pad) => {
    const [x0, x1] = colRange(y0, y1);
    const left = Math.max(0, x0 - pad), top = Math.max(0, y0 - pad);
    return {
      left,
      top,
      width: Math.min(width, x1 + pad + 1) - left,
      height: Math.min(height, y1 + pad + 1) - top,
    };
  };
  const base = () => sharp(rgba, { raw: { width, height, channels: 4 } });

  const mark = region(blocks[0][0], blocks[0][1], 4);
  console.log("hexagono:", mark);

  const out = (p) => {
    fs.mkdirSync(path.dirname(p), { recursive: true });
    return p;
  };
  const transparent = { r: 0, g: 0, b: 0, alpha: 0 };
  const black = { r: 0, g: 0, b: 0, alpha: 1 };

  // El hexagono, transparente: login, barra de navegacion y encabezados.
  await base().extract(mark).resize({ height: 176 }).png().toFile(out("components/brand/logo-mark.png"));
  // Para los correos: se sirve desde una direccion fija.
  await base().extract(mark).resize({ height: 112 }).png().toFile(out("public/logo-email.png"));

  // Icono de la pestana y del telefono: el hexagono sobre negro, con margen.
  const square = async (size, inner, file) => {
    const buf = await base()
      .extract(mark)
      .resize({ width: inner, height: inner, fit: "contain", background: transparent })
      .png()
      .toBuffer();
    await sharp({ create: { width: size, height: size, channels: 4, background: black } })
      .composite([{ input: buf, gravity: "centre" }])
      .png()
      .toFile(out(file));
  };
  await square(256, 208, "app/icon.png");
  await square(180, 140, "app/apple-icon.png");

  for (const f of ["components/brand/logo-mark.png", "public/logo-email.png", "app/icon.png", "app/apple-icon.png"]) {
    const m = await sharp(f).metadata();
    console.log(f, `${m.width}x${m.height}`, fs.statSync(f).size, "bytes");
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
