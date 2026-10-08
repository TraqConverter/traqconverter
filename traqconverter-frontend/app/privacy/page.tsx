import type { Metadata } from "next"
import Link from "next/link"

import LegalPage, { TableScroll } from "@/components/legal/LegalPage"
import { COMPANY } from "@/lib/company"

export const metadata: Metadata = {
  title: "Privacy Policy · OnlineDocTranslator",
  description: `How ${COMPANY.name} handles personal data in OnlineDocTranslator.`,
}

const mail = `mailto:${COMPANY.email}`

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      updated="8 October 2026"
      intro="This policy explains what personal data OnlineDocTranslator handles, why, who else processes it, how long we keep it, and the rights you have."
    >
      <h2 id="who-we-are">1. Who we are</h2>
      <p>
        OnlineDocTranslator ({COMPANY.site.replace("https://", "")}) is run by {COMPANY.name}, a company registered
        in England and Wales under company number {COMPANY.companyNumber}, registered office {COMPANY.address}{" "}
        (&quot;we&quot;, &quot;us&quot;).
      </p>
      <p>
        We handle personal data under the UK General Data Protection Regulation (UK GDPR) and the UK Data Protection
        Act 2018 and, for users in the European Union, the EU General Data Protection Regulation (EU GDPR). In this
        policy, &quot;GDPR&quot; means whichever of the two applies to you.
      </p>
      <p>
        For any privacy question or request, write to <a href={mail}>{COMPANY.email}</a>.
      </p>

      <h2 id="roles">2. Our role: controller or processor</h2>
      <ul>
        <li>
          <strong>Account, team and billing data.</strong>{" "}We decide how this data is used, so we are the{" "}
          <strong>controller</strong>.
        </li>
        <li>
          <strong>Documents you upload and everything made from them</strong>{" "}(text, translations, memory, glossary,
          templates, certification files). You, or the client you work for, decide why these are processed, so you
          are the <strong>controller</strong>{" "}and we are your <strong>processor</strong>. We process them only to
          provide the service to you. A data processing agreement (DPA) is available on request at{" "}
          <a href={mail}>{COMPANY.email}</a>.
        </li>
      </ul>
      <p>
        If you are a translator&apos;s client and your personal data is in a document they uploaded, please contact
        that translator or agency first: they decide how your document is handled. We will help them answer you.
      </p>

      <h2 id="data">3. What data we handle</h2>
      <h3>Account and team</h3>
      <ul>
        <li>Email address, full name, and your password, which we store only as a one-way (bcrypt) hash.</li>
        <li>Your team, your role in it, and invitations you send or receive (the invitee&apos;s email and role).</li>
        <li>The logos, stamps and signatures your team uploads to Media.</li>
        <li>The date and time you accepted the Terms of Service.</li>
      </ul>
      <h3>Your content</h3>
      <ul>
        <li>The documents you upload (PDF, images, DOCX) and the text read from them.</li>
        <li>Translations, edits and saved versions, comments, and instructions you give the AI.</li>
        <li>
          Translation memory, glossary and learned terms, and document templates built from finished documents.
        </li>
        <li>Certification files and templates you upload, stored with a SHA-256 fingerprint.</li>
        <li>Delivery links you create for clients, with their expiry date and download count.</li>
        <li>
          For protected delivery links (paid before download): the amount, when the client said they had paid, when
          the link was paid or unlocked, and the download count. We also store your team&apos;s PayPal.me name. We
          don&apos;t collect or store the names or email addresses of your clients. A client who pays on PayPal, or
          by bank transfer or another method outside the service, pays you directly, so we never receive or store
          their payment details. If the client tells us they have paid, we record when and email you.
        </li>
        <li>
          When a client pays a protected link through Stripe, Stripe collects the payment details on the
          translator&apos;s own Stripe account, as the translator&apos;s payment provider. We only receive the payment
          status, the amount and the payment reference, and we store your team&apos;s Stripe account ID. We never
          receive card or bank details.
        </li>
      </ul>
      <p>
        These documents often contain personal data about third parties, sometimes of a sensitive kind (for
        example identity documents, civil status records or medical reports).
      </p>
      <h3>Usage and billing</h3>
      <ul>
        <li>
          AI usage records: which action ran, which model, how many tokens it used and what it cost. We use these to
          meter credits and to price the service.
        </li>
        <li>Your plan, subscription status, credit balance and credit history.</li>
        <li>
          Payment data is handled by Stripe. We never see or store your card number. We receive your Stripe customer
          and subscription identifiers and the status of your payments. At checkout Stripe also collects your billing
          address, which appears on your invoices.
        </li>
      </ul>
      <h3>Technical data</h3>
      <ul>
        <li>
          Server logs kept by our hosting providers (such as IP address, time and requested address), used to run
          and protect the service.
        </li>
        <li>
          Small items stored in your browser to keep you signed in. See the <Link href="/cookies">Cookie Policy</Link>.
          We do not use analytics or advertising trackers.
        </li>
      </ul>

      <h2 id="purposes">4. Why we use it, and on what legal basis</h2>
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Purpose</th>
              <th>Legal basis (GDPR)</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Create and run your account and team; translate, edit, store and deliver your documents</td>
              <td>Performance of a contract, Art. 6(1)(b)</td>
            </tr>
            <tr>
              <td>Process payments, issue invoices, keep accounting records</td>
              <td>Contract, Art. 6(1)(b); legal obligation, Art. 6(1)(c)</td>
            </tr>
            <tr>
              <td>Send service emails, such as team invitations</td>
              <td>Performance of a contract, Art. 6(1)(b)</td>
            </tr>
            <tr>
              <td>Keep the service secure, prevent abuse, fix errors, measure AI costs</td>
              <td>Legitimate interest, Art. 6(1)(f)</td>
            </tr>
            <tr>
              <td>Answer requests and defend legal claims</td>
              <td>Legitimate interest, Art. 6(1)(f); legal obligation, Art. 6(1)(c)</td>
            </tr>
          </tbody>
        </table>
      </TableScroll>
      <p>
        For your content we act on your instructions as processor; the legal basis for processing it, including any
        special categories of data, is yours as controller.
      </p>
      <p>
        We don&apos;t send marketing emails, we don&apos;t sell personal data, and we don&apos;t make decisions about
        you based solely on automated processing that have legal or similarly significant effects.
      </p>

      <h2 id="ai">5. How AI processing works</h2>
      <p>
        To translate a document, read scanned pages, rebuild the layout and answer requests in the editor, the
        relevant text and page images are sent to our AI provider, Anthropic, through its commercial API. If you or a
        team member choose an OpenAI engine in the editor, that request goes to OpenAI instead.
      </p>
      <ul>
        <li>
          <strong>No training.</strong>{" "}Under the providers&apos; commercial API terms, data sent through the API is
          not used to train their models. We don&apos;t train models on your documents either.
        </li>
        <li>
          The providers may keep requests for a limited time under their own terms, for example to detect abuse.
        </li>
        <li>
          Corrections you make are reused only inside your own team (translation memory, glossary, templates). They
          are never shared with other customers.
        </li>
      </ul>

      <h2 id="processors">6. Who processes data for us</h2>
      <p>We use these sub-processors. Each is bound by a data processing agreement.</p>
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>What it does</th>
              <th>Location</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Anthropic</td>
              <td>AI processing: translation, reading scans, layout rebuild, editor assistant</td>
              <td>United States</td>
            </tr>
            <tr>
              <td>OpenAI</td>
              <td>AI processing, only when an OpenAI engine is chosen for a document</td>
              <td>United States</td>
            </tr>
            <tr>
              <td>Supabase</td>
              <td>Database and file storage for your account and documents</td>
              <td>EU (Ireland)</td>
            </tr>
            <tr>
              <td>Railway</td>
              <td>API hosting: the servers that run the application and process your documents</td>
              <td>EU or US region, as configured</td>
            </tr>
            <tr>
              <td>Vercel</td>
              <td>Hosting of the website and web app</td>
              <td>Global edge network</td>
            </tr>
            <tr>
              <td>Stripe</td>
              <td>Payment processing for {COMPANY.name}: payments, subscriptions and invoices</td>
              <td>EU and United States</td>
            </tr>
            <tr>
              <td>Resend</td>
              <td>Sending service emails, such as team invitations</td>
              <td>United States</td>
            </tr>
          </tbody>
        </table>
      </TableScroll>
      <p>
        Stripe also acts as an independent controller for some purposes, such as fraud prevention and its own legal
        obligations; see Stripe&apos;s privacy policy. We will update this list before adding a new sub-processor.
      </p>

      <h2 id="transfers">7. International transfers</h2>
      <p>
        Your documents and account data are stored in the EU (Ireland). We run the service from the United Kingdom,
        which the European Commission recognises as giving adequate protection to personal data. Some providers above
        are based in, or process data in, the United States. Where data leaves the UK or the European Economic Area,
        we rely on safeguards such as the European Commission&apos;s Standard Contractual Clauses with the UK
        Addendum, or the EU-US Data Privacy Framework and its UK Extension, where the provider is certified. You can
        ask us for more information about these safeguards.
      </p>

      <h2 id="retention">8. How long we keep data</h2>
      <ul>
        <li>
          <strong>Projects</strong>{" "}(the uploaded document, its text, translations, versions, comments, and its
          translation memory entries) stay until you delete the project or your account. We don&apos;t delete
          projects automatically after a set period, including after a trial or a subscription ends.
        </li>
        <li>
          <strong>Templates and learned terms</strong>{" "}built from a project stay in your team&apos;s library after the
          project is deleted, until you delete them or the account.
        </li>
        <li>
          <strong>Delivery links</strong>{" "}expire after 1, 7 or 30 days, as you choose, or when you revoke them. The
          file behind a link is deleted when you revoke it, or 7 days after it expires. A protected link&apos;s
          watermarked preview images are deleted when you unlock or revoke it, or with the file.
        </li>
        <li>
          <strong>Uploaded files waiting to become templates</strong>{" "}are discarded after 24 hours if you don&apos;t
          save them.
        </li>
        <li>
          <strong>Your account</strong>{" "}stays until you delete it from Settings. If you own a team, deleting your
          account also deletes the team with its projects, memory, glossary, templates, certification files and credit
          history, and the stored files behind them. If you are
          a team member, only your own account is removed; the team&apos;s work stays with its owner.
        </li>
        <li>
          <strong>AI usage records</strong>{" "}are kept for cost accounting. When the related account or project is
          deleted, the link to it is removed.
        </li>
        <li>
          <strong>Invoices and accounting records</strong>{" "}are kept for as long as company and tax law
          requires (in the UK, generally 6 years from the end of the financial year).
        </li>
        <li>
          Deleted data can remain in our providers&apos; backups for a limited period before it is overwritten.
        </li>
      </ul>

      <h2 id="security">9. Security</h2>
      <p>
        All connections use HTTPS, stored files are encrypted at rest, and passwords are stored only as hashes.
        Projects are visible only to your team, and roles control what each member can do. Delivery links use
        random tokens that we store only in hashed form.
      </p>

      <h2 id="rights">10. Your rights</h2>
      <p>Under the GDPR you can ask us to:</p>
      <ul>
        <li>give you access to your personal data and a copy of it;</li>
        <li>correct data that is wrong or incomplete;</li>
        <li>delete your data;</li>
        <li>restrict how we use it;</li>
        <li>give you your data in a portable format;</li>
        <li>stop using it where we rely on legitimate interest (objection).</li>
      </ul>
      <p>
        You can change your name in Settings and delete projects or your whole account at any time.
        For anything else, write to <a href={mail}>{COMPANY.email}</a>. We answer within one month. We may
        ask you to confirm your identity first.
      </p>
      <p>
        Where we are a processor (your documents), requests from the people named in them should go to the customer
        who uploaded them; we will help that customer respond.
      </p>
      <p>
        You also have the right to lodge a complaint with a supervisory authority. In the UK this is the{" "}
        <a href="https://ico.org.uk" target="_blank" rel="noopener noreferrer">
          Information Commissioner&apos;s Office (ICO)
        </a>
        . If you live in the EU, you can complain to the data protection authority of your country of residence.
      </p>

      <h2 id="children">11. Children</h2>
      <p>OnlineDocTranslator is a professional tool. It is not meant for anyone under 18.</p>

      <h2 id="changes">12. Changes to this policy</h2>
      <p>
        If we change this policy in a way that matters, we will tell you by email or in the app before the change
        takes effect. The date at the top shows the latest version.
      </p>

      <h2 id="contact">13. Contact</h2>
      <p>
        {COMPANY.name}, {COMPANY.address}. Email for privacy requests:{" "}
        <a href={mail}>{COMPANY.email}</a>.
      </p>
    </LegalPage>
  )
}
