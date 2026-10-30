// Header media of a template send: an uploaded file (Hub media id) or a public HTTPS link that Meta fetches.
import { attachmentFormatError, attachmentMaxBytes, sizeError } from "../components/messages/attachmentFormats.js";

const CHANNEL_KIND = { image: "photo", video: "video", document: "document" };
const PRIVATE_SUFFIXES = [".localhost", ".local", ".internal", ".intranet", ".lan", ".home.arpa"];

export function headerChannelKind(format) {
  return CHANNEL_KIND[format];
}

function isPrivateAddress(host) {
  const parts = host.split(".").map(Number);
  if (parts.length === 4 && parts.every((part) => Number.isInteger(part) && part >= 0 && part <= 255)) {
    const [first, second] = parts;
    return first === 0 || first === 10 || first === 127 || first >= 224 || (first === 169 && second === 254) ||
      (first === 172 && second >= 16 && second <= 31) || (first === 192 && second === 168) || (first === 100 && second >= 64 && second <= 127);
  }
  return host.startsWith("[");
}

// The server checks the same rules; this message only helps before sending.
export function headerLinkError(value) {
  let url;
  try {
    url = new URL(String(value || "").trim());
  } catch {
    return "Paste a full link that starts with https://";
  }
  if (url.protocol !== "https:") return "Use a secure link that starts with https://";
  if (url.username || url.password) return "Remove the user name and password from the link.";
  if (url.hash || url.href.length > 2048) return "Use a shorter link without a # part.";
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  const last = host.split(".").at(-1);
  if (!host.includes(".") || PRIVATE_SUFFIXES.some((suffix) => host.endsWith(suffix)) || isPrivateAddress(host) || /^\d+$/.test(last))
    return "Use a public link. WhatsApp cannot open internal addresses.";
  return "";
}

export function linkFileName(value) {
  try {
    const name = decodeURIComponent(new URL(value).pathname.split("/").at(-1) || "");
    return name.replace(/[\\/"\u0000-\u001f]/g, "").slice(0, 120) || "document";
  } catch {
    return "document";
  }
}

export function headerFileError(capabilities, format, file) {
  const formatError = attachmentFormatError(capabilities, "WhatsApp", CHANNEL_KIND[format], file.name);
  if (formatError) return formatError;
  return sizeError(file.size, attachmentMaxBytes(capabilities, "WhatsApp", CHANNEL_KIND[format]));
}

export function readBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(Error("Could not read this file."));
    reader.readAsDataURL(file);
  });
}

// Provider shape of one header media value; a document keeps its file name.
export function headerMediaParameter(format, value) {
  if (!value || typeof value !== "object") return null;
  const media = value.id ? { id: String(value.id) } : value.link ? { link: String(value.link) } : null;
  if (!media) return null;
  if (format === "document" && value.filename) media.filename = String(value.filename);
  return { type: format, [format]: media };
}
