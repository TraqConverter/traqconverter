export const COMPANY = {
  name: "Espresso Translations S.r.l.",
  vat: "10186210968",
  address: "Foro Buonaparte 59, 20121 Milano, Italy",
  // Shown only in the Privacy Policy, as the contact for data-protection requests (GDPR Art. 13).
  privacyEmail: "info@espressotranslations.com",
  site: "https://www.onlinedoctranslator.ai",
  api: "https://api.onlinedoctranslator.ai",
} as const

export const LEGAL_LINKS: [string, string][] = [
  ["Terms", "/terms"],
  ["Privacy", "/privacy"],
  ["Cookies", "/cookies"],
]

export const VAT_NOTE =
  "Prices exclude VAT. Italian customers and EU consumers pay VAT; EU businesses with a valid VAT number are reverse-charged; customers outside the EU pay no VAT."
