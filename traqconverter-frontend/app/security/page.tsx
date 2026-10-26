import type { Metadata } from "next"
import Link from "next/link"

import LegalPage from "@/components/legal/LegalPage"
import SubProcessorTable from "@/components/legal/SubProcessorTable"
import { COMPANY } from "@/lib/company"

export const metadata: Metadata = {
  title: "Security · OnlineDocTranslator",
  description: "How OnlineDocTranslator protects the documents you translate: access, storage, encryption, deletion and AI processing.",
}

const mail = `mailto:${COMPANY.email}`

export default function SecurityPage() {
  return (
    <LegalPage
      title="Security"
      eyebrow="TRUST"
      updated="23 October 2026"
      intro="Certified work means passports, birth certificates, court papers and medical reports. This page sets out, in plain words, what OnlineDocTranslator does to protect them."
    >
      <h2 id="access">1. Who can see your documents</h2>
      <ul>
        <li>
          Every project belongs to a team. The app opens a project only for the owner and members of that team. Anyone
          else who tries a project&apos;s address gets &quot;not found&quot;, so they can&apos;t even tell it exists.
        </li>
        <li>
          Roles decide who can do what. The owner and admins manage billing, payments and Media. The owner, admins and
          project managers can certify, run a translation again, unlock client links and delete in bulk. A project can
          be deleted by the person who uploaded it, the owner, an admin or a project manager.
        </li>
        <li>
          Our internal usage report shows file names, team names, page counts and AI costs, which we need for billing.
          It doesn&apos;t show what your documents say. When we do have to open your content, the{" "}
          <Link href="/terms#confidentiality">confidentiality terms</Link> limit when we may.
        </li>
      </ul>

      <h2 id="storage">2. Where your data is stored</h2>
      <p>
        Your account data, documents and translations are stored with Supabase in the EU, in Ireland (AWS region
        eu-west-1), in both the database and the file storage. To translate a document, the app sends its text and
        page images to the AI providers listed in <a href="#sub-processors">section 9</a>, which are in the United
        States.
      </p>

      <h2 id="encryption">3. Encryption and links</h2>
      <ul>
        <li>
          Every connection to the website, the app and our servers uses HTTPS (TLS). Our servers also send HSTS, which
          tells your browser to use only HTTPS from then on.
        </li>
        <li>Stored data is encrypted at rest by our storage provider.</li>
        <li>Passwords are never stored. We keep only a one-way (bcrypt) hash.</li>
        <li>
          When you open or download a file in the app, it comes from a signed link that stops working after one hour.
        </li>
        <li>
          A client link carries a long random token. We look it up by a one-way hash and keep the token itself only in
          encrypted form, so your team can copy the link again.
        </li>
      </ul>

      <h2 id="deletion">4. Deletion</h2>
      <ul>
        <li>
          A project is deleted automatically 90 days after its translation is completed, or 90 days after upload if it
          never completes. Running the translation again starts the 90 days again. The date is shown on the project,
          and the uploader and the assignee get a notice 7 days before.
        </li>
        <li>
          Deletion covers the original, the translations and exported files, saved versions, page images, certified
          copies, client links and their files, and comments.
        </li>
        <li>
          Your team&apos;s translation memory, glossary and templates are kept, because they are working assets. They
          stay until you delete them or the account.
        </li>
        <li>
          You can delete a project yourself at any time, and your whole account from Settings. When a team owner
          deletes their account, the team and all its data go with it.
        </li>
        <li>
          The file behind a client link is deleted when you revoke the link, or 7 days after it expires.
        </li>
        <li>
          You can also ask us to delete data at <a href={mail}>{COMPANY.email}</a>. Deleted data can stay in our
          providers&apos; backups for a limited time before it is overwritten.
        </li>
      </ul>

      <h2 id="ai">5. AI processing, and no training</h2>
      <ul>
        <li>
          Translation, reading scans and the editor assistant run on Anthropic&apos;s commercial API. If someone in
          your team picks GPT-4.1 for a project, OpenAI&apos;s commercial API writes that translation, and Anthropic
          still reads the scans and rebuilds the layout.
        </li>
        <li>
          We don&apos;t train AI models on your documents, and under those providers&apos; commercial API terms they
          don&apos;t either.
        </li>
        <li>
          What the app learns from your corrections (translation memory, glossary, templates) stays inside your team.
          It is never shared with other customers.
        </li>
        <li>Questions asked in the Help chat are sent to Anthropic to answer them, and aren&apos;t stored.</li>
      </ul>

      <h2 id="client-links">6. Links you send to clients</h2>
      <ul>
        <li>
          A client link expires after 1, 7 or 30 days, as you choose, and you can revoke it at any time. Your client
          needs no account.
        </li>
        <li>
          On a link protected until paid, the file itself is not sent until you unlock it. Until then the client sees
          only page images made on our server, with &quot;PREVIEW – NOT VALID – UNPAID&quot; and the date repeated
          across the whole page, and names, numbers and other details blurred. The pages of the original are left
          out of the preview.
        </li>
        <li>
          A client can leave an email address to hear when the document is ready. We use it once for that notice,
          then delete it. It is also deleted if the link is revoked, expires or is deleted first, and nobody on your
          team can see it.
        </li>
      </ul>

      <h2 id="sign-in">7. Signing in</h2>
      <ul>
        <li>
          After 10 wrong passwords within 15 minutes, the account is locked for 15 minutes. Sign-in attempts are also
          limited per network address.
        </li>
        <li>
          A session lasts 24 hours, then you sign in again. Signing out, changing your password or resetting it ends
          your other sessions.
        </li>
        <li>Password reset links work once and expire after 60 minutes.</li>
        <li>
          Our pages and servers send security headers: Strict-Transport-Security, Content-Security-Policy on the web
          app, X-Frame-Options (so other sites can&apos;t frame our pages), X-Content-Type-Options, Referrer-Policy
          and Permissions-Policy (no camera, microphone or location).
        </li>
      </ul>

      <h2 id="payments">8. Payments</h2>
      <p>
        Subscriptions and credit packs are paid through Stripe Checkout, and the billing portal is Stripe&apos;s. We
        never see or store your card number. When your clients pay you through a protected link, they pay on your own
        Stripe account or on PayPal, and we don&apos;t receive their card or bank details either.
      </p>

      <h2 id="sub-processors">9. Sub-processors</h2>
      <p>These providers process data for us. The same list is in our <Link href="/privacy#processors">Privacy Policy</Link>.</p>
      <SubProcessorTable />

      <h2 id="dpa">10. Data processing agreement</h2>
      <p>
        For the documents you upload, you are the controller and we are your processor. Our{" "}
        <Link href="/dpa">data processing agreement</Link>{" "}sets that out under Article 28 of the GDPR, and you can
        save it as a PDF for your records.
      </p>

      <h2 id="report">11. Reporting a security issue</h2>
      <p>
        If you think you have found a security problem, email <a href={mail}>{COMPANY.email}</a>{" "}with what you
        found and the steps to see it. Please don&apos;t access other people&apos;s data or disrupt the service while
        you look.
      </p>
    </LegalPage>
  )
}
