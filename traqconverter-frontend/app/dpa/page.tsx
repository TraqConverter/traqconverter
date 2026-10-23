import type { Metadata } from "next"
import Link from "next/link"

import LegalPage from "@/components/legal/LegalPage"
import PrintButton from "@/components/legal/PrintButton"
import SubProcessorTable from "@/components/legal/SubProcessorTable"
import { COMPANY } from "@/lib/company"

export const metadata: Metadata = {
  title: "Data Processing Agreement · OnlineDocTranslator",
  description: `The GDPR Article 28 data processing agreement between ${COMPANY.name} and OnlineDocTranslator customers.`,
}

const mail = `mailto:${COMPANY.email}`

export default function DpaPage() {
  return (
    <LegalPage
      title="Data Processing Agreement"
      updated="23 October 2026"
      intro="This agreement covers the personal data in the documents you upload to OnlineDocTranslator. It sets out what we, as your processor, do with that data and what we owe you under Article 28 of the GDPR."
      actions={<PrintButton />}
    >
      <h2 id="parties">1. Parties and how this agreement applies</h2>
      <ul>
        <li>
          <strong>Processor:</strong>{" "}{COMPANY.name}, a company registered in England and Wales under company number{" "}
          {COMPANY.companyNumber}, registered office {COMPANY.address}, email <a href={mail}>{COMPANY.email}</a>{" "}
          (&quot;we&quot;, &quot;us&quot;).
        </li>
        <li>
          <strong>Controller:</strong>{" "}the customer who holds an OnlineDocTranslator account and has accepted our{" "}
          <Link href="/terms">Terms of Service</Link>: for a team, the team owner on behalf of the team (&quot;you&quot;).
        </li>
      </ul>
      <p>
        This agreement forms part of the Terms of Service and applies whenever the service processes personal data on
        your behalf. Where it conflicts with the Terms on the protection of personal data, this agreement wins. If you
        need a countersigned copy, write to <a href={mail}>{COMPANY.email}</a>.
      </p>
      <p>
        &quot;GDPR&quot; means the UK GDPR and the UK Data Protection Act 2018 and, where it applies, the EU General
        Data Protection Regulation (EU) 2016/679. Terms such as &quot;personal data&quot;, &quot;processing&quot;,
        &quot;controller&quot;, &quot;processor&quot;, &quot;data subject&quot; and &quot;personal data breach&quot; have
        their GDPR meanings. &quot;Customer content&quot; means the documents you upload and everything made from them:
        text, translations, saved versions, comments, translation memory, glossary, templates, certification files
        and client delivery links.
      </p>

      <h2 id="subject">2. Subject matter and duration</h2>
      <p>
        We process personal data in customer content to provide OnlineDocTranslator to you. We do so for as long as
        you use the service, and afterwards until the data is deleted or returned under section 13.
      </p>

      <h2 id="nature">3. Nature and purpose of the processing</h2>
      <p>
        Storing your documents; reading scanned pages and images; translating text with AI; rebuilding the layout as
        an editable document; running quality checks; adding your certification page; exporting files; delivering
        files to your clients through links you create; and keeping the translation memory, glossary and templates
        your team builds. We process this data only to provide the service to you.
      </p>

      <h2 id="data">4. Types of personal data</h2>
      <p>Whatever the documents you upload contain. For certified translation this typically includes:</p>
      <ul>
        <li>identity data: names, dates and places of birth, nationality, sex, photographs, signatures, identity and passport numbers;</li>
        <li>contact data: addresses, phone numbers and email addresses;</li>
        <li>civil-status data: birth, marriage, divorce and death records, family relationships;</li>
        <li>education and employment records: diplomas, transcripts, references and contracts;</li>
        <li>financial and administrative data: bank statements, tax and social-security numbers;</li>
        <li>
          special categories of personal data (Article 9 GDPR), where documents contain them: for example health data
          in medical reports, or religion or ethnic origin recorded in civil-status documents;
        </li>
        <li>personal data relating to criminal convictions and offences (Article 10 GDPR), for example in police certificates or court records;</li>
        <li>the email address a client gives on a protected link, if they choose to give one.</li>
      </ul>
      <p>
        You decide what you upload. You are responsible for having a lawful basis for processing these data,
        including a condition under Article 9 or Article 10 where they apply.
      </p>

      <h2 id="subjects">5. Data subjects</h2>
      <ul>
        <li>the people named in the documents you upload, usually your clients and members of their families;</li>
        <li>other people who appear in those documents, such as officials, witnesses, doctors or employers;</li>
        <li>the clients you send delivery links to.</li>
      </ul>
      <p>
        Your own account, team and billing data are not covered by this agreement: for those we are the controller,
        as described in our <Link href="/privacy">Privacy Policy</Link>.
      </p>

      <h2 id="obligations">6. Our obligations as processor</h2>
      <ul>
        <li>
          We process personal data only on your documented instructions. Those instructions are the Terms of Service,
          this agreement, and what you and your team do in the service (uploading, editing, sharing, deleting). We
          will process it otherwise only where UK or EU law requires us to, and then we will tell you first unless
          that law forbids it.
        </li>
        <li>We will tell you if we think an instruction breaks the GDPR.</li>
        <li>
          We don&apos;t use customer content for our own purposes. We don&apos;t sell it, and we don&apos;t use it to
          train AI models.
        </li>
        <li>We keep a record of our processing activities as Article 30(2) GDPR requires.</li>
      </ul>

      <h2 id="confidentiality">7. Confidentiality</h2>
      <p>
        Everyone we authorise to process customer content is bound by a duty of confidentiality. We access customer
        content only when needed to provide the service, to help you when you ask for support, to keep the service
        secure, or when the law requires it.
      </p>

      <h2 id="security">8. Security</h2>
      <p>
        We apply technical and organisational measures appropriate to the risk, as Article 32 GDPR requires. They are
        described on our <Link href="/security">Security page</Link>{" "}and include:
      </p>
      <ul>
        <li>access limited to the members of the team that owns a project, with roles for sensitive actions;</li>
        <li>storage in the EU (Ireland); encryption in transit (HTTPS) and at rest;</li>
        <li>passwords stored only as hashes, sign-in lockout after repeated failures, and sessions that expire;</li>
        <li>short-lived signed links for file downloads, and client links stored only as hashes;</li>
        <li>automatic deletion of projects 90 days after the translation is completed.</li>
      </ul>
      <p>We may update these measures over time, but not in a way that lowers the overall level of protection.</p>

      <h2 id="sub-processors">9. Sub-processors</h2>
      <p>
        You give us general authorisation to use sub-processors. Those we use today are listed below and in our{" "}
        <Link href="/privacy#processors">Privacy Policy</Link>:
      </p>
      <SubProcessorTable />
      <ul>
        <li>
          We will tell you by email or in the app before we add or replace a sub-processor that processes customer
          content, so that you can object. If you object on reasonable data-protection grounds and we can&apos;t
          resolve it, you can stop using the service and delete your account.
        </li>
        <li>
          We bind each sub-processor by a written contract to data-protection obligations that give at least the
          protection set out in this agreement. We remain responsible to you for their work.
        </li>
      </ul>

      <h2 id="transfers">10. International transfers</h2>
      <p>
        Customer content is stored in the EU (Ireland). We are based in the United Kingdom, which the European
        Commission recognises as giving adequate protection. Some sub-processors are based in, or process data in, the
        United States. Where personal data leaves the UK or the European Economic Area, we make sure an appropriate
        safeguard is in place, such as the European Commission&apos;s Standard Contractual Clauses with the UK
        Addendum, the UK International Data Transfer Agreement, or the EU-US Data Privacy Framework and its UK
        Extension where the provider is certified.
      </p>

      <h2 id="assistance">11. Helping you meet your obligations</h2>
      <ul>
        <li>
          <strong>Data subject requests.</strong>{" "}The service lets you find, correct, export and delete customer
          content yourself. Where you need more, we will help you answer requests to exercise the rights in Chapter
          III of the GDPR. If a data subject contacts us directly about customer content, we will pass the request to
          you and won&apos;t answer it ourselves unless you ask us to.
        </li>
        <li>
          <strong>Other obligations.</strong>{" "}Taking into account the information available to us, we will help you
          with security (Article 32), breach notification (Articles 33 and 34), data protection impact assessments and
          prior consultation (Articles 35 and 36).
        </li>
      </ul>

      <h2 id="breach">12. Personal data breaches</h2>
      <p>
        We will notify you without undue delay after we become aware of a personal data breach affecting customer
        content. We will tell you what we know: the nature of the breach, the categories and approximate number of
        data subjects and records concerned, its likely consequences, and the measures taken or proposed. Where we
        don&apos;t yet know everything, we will send what we have and follow up as we learn more.
      </p>

      <h2 id="deletion">13. Deletion and return of data</h2>
      <ul>
        <li>
          You can download your translations and files at any time while your account is active. Keep your own copies
          of finished work.
        </li>
        <li>
          Projects are deleted automatically 90 days after the translation is completed, or 90 days after upload if it
          never completes, as described in the <Link href="/terms#data">Terms</Link>. You can delete any project
          sooner.
        </li>
        <li>
          Translation memory, glossary and templates stay until you delete them or the account. When a team owner
          deletes their account, the team and all its customer content are deleted.
        </li>
        <li>
          At the end of the service we delete customer content as above, unless UK or EU law requires us to keep it.
          Deleted data can stay in our providers&apos; backups for a limited period until it is overwritten.
        </li>
      </ul>

      <h2 id="audits">14. Information and audits</h2>
      <p>
        On reasonable request we will give you the information needed to show that we meet Article 28 GDPR. We will
        first answer in writing, for example with answers to a security questionnaire and the relevant details of our
        sub-processors. If that isn&apos;t enough, or a supervisory authority requires it, we will allow an audit by
        you or an auditor you appoint who is bound by confidentiality, on reasonable notice, during business hours,
        at your cost, and no more than once a year unless a breach has occurred.
      </p>

      <h2 id="general">15. Liability, law and changes</h2>
      <ul>
        <li>Each party&apos;s liability under this agreement is subject to the limits in the Terms of Service.</li>
        <li>
          This agreement is governed by the law of England and Wales, like the Terms. Where the EU GDPR requires the
          law of an EU member state for the transfer safeguards in section 10, that law applies to them.
        </li>
        <li>
          We may update this agreement to reflect changes in the law or in the service. We will tell you about
          changes that matter in the same way as changes to the Terms.
        </li>
      </ul>

      <h2 id="contact">16. Contact</h2>
      <p>
        {COMPANY.name}, {COMPANY.address}. Email: <a href={mail}>{COMPANY.email}</a>.
      </p>
    </LegalPage>
  )
}
