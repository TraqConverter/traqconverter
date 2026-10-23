export type SubProcessor = {
  name: string
  purpose: string
  location: string
}

// One list for Privacy, Security and the DPA. Change it here, and tell customers before a new one starts.
export const SUB_PROCESSORS: SubProcessor[] = [
  {
    name: "Anthropic",
    purpose: "AI processing: translation, reading scans, layout rebuild, editor assistant and the Help chat",
    location: "United States",
  },
  {
    name: "OpenAI",
    purpose: "AI translation, only for projects where GPT-4.1 (OpenAI) is chosen",
    location: "United States",
  },
  {
    name: "Supabase",
    purpose: "Database and file storage for your account and documents",
    location: "EU (Ireland)",
  },
  {
    name: "Railway",
    purpose: "API hosting: the servers that run the application and process your documents",
    location: "EU or US region, as configured",
  },
  {
    name: "Vercel",
    purpose: "Hosting of the website and web app",
    location: "Global edge network",
  },
  {
    name: "Stripe",
    purpose: "Payment processing for our own plans and credit packs: payments, subscriptions and invoices",
    location: "EU and United States",
  },
  {
    name: "Resend",
    purpose: "Sending service emails, such as team invitations, password resets and ready notices",
    location: "United States",
  },
]
