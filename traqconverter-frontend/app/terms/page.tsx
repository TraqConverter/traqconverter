import type { Metadata } from "next"
import Link from "next/link"

import LegalPage from "@/components/legal/LegalPage"
import PlanTable from "@/components/legal/PlanTable"
import { COMPANY } from "@/lib/company"

export const metadata: Metadata = {
  title: "Terms of Service · OnlineDocTranslator",
  description: `The terms for using OnlineDocTranslator, sold by ${COMPANY.name}.`,
}

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Service"
      updated="8 October 2026"
      intro="These terms are the agreement between you and us for using OnlineDocTranslator. We've kept them short and plain. Please read them before you sign up."
    >
      <h2 id="who">1. Who we are</h2>
      <p>
        OnlineDocTranslator is provided by {COMPANY.name}, a company registered in England and Wales under company
        number {COMPANY.companyNumber}, registered office {COMPANY.address}{" "}(&quot;we&quot;, &quot;us&quot;). By creating an account you accept these terms and
        confirm you have read our <Link href="/privacy">Privacy Policy</Link>.
      </p>
      <p>
        These terms apply to everyone who uses the service, including people who join a team by invitation. We sell
        to businesses and to consumers. Where a term treats consumers differently, it says so.
      </p>

      <h2 id="service">2. The service</h2>
      <p>
        OnlineDocTranslator is an online workspace for professional translators and agencies. You upload a document (PDF,
        image or DOCX); the service produces an AI draft translation with the original layout rebuilt, which you
        review and edit. Depending on your plan it also offers translation memory, glossaries, templates,
        certification pages, client delivery links and team collaboration.
      </p>
      <p>
        OnlineDocTranslator is a software tool. We don&apos;t translate, review, certify or deliver documents
        ourselves, and we don&apos;t provide translation services to you or to your clients.
      </p>
      <p>You must be at least 18 to use the service.</p>

      <h2 id="accounts">3. Accounts and teams</h2>
      <ul>
        <li>Give accurate details when you sign up, and keep your password secret.</li>
        <li>
          You are responsible for what happens under your account. If you think someone else has used it, change
          your password and tell us straight away.
        </li>
        <li>
          Every account belongs to a team. The person who creates the team is its owner. The owner can invite
          members, up to the team size of the plan, and give each one a role (admin, project manager, reviewer or
          member).
        </li>
        <li>
          The owner and team admins manage the subscription and the billing portal, the team&apos;s payment
          settings, its stamp and its media. Every member can see the team&apos;s credit balance and credit history.
        </li>
        <li>
          Projects and libraries (memory, glossary, templates, certifications) belong to the team. If the owner
          deletes their account, the team and its data are deleted too. If a member leaves, the team&apos;s work stays.
        </li>
        <li>Don&apos;t share a login between several people; invite them as team members instead.</li>
      </ul>

      <h2 id="trial">4. Free trial</h2>
      <p>
        New accounts get a 7-day free trial with 3 pages. During the trial you can translate and edit, but you
        can&apos;t download results, invite team members or buy credit packs, and some features (translation
        memory, glossary, templates, media, certifications) aren&apos;t available. No card is needed. Trial credits
        you don&apos;t use end with the trial. When the trial ends, you need a paid plan to continue.
      </p>

      <h2 id="credits">5. Plans and credits</h2>
      <ul>
        <li>
          <strong>1 credit = 1 page.</strong>{" "}Translating a document uses one credit per page, taken when you start
          the job. Credits are shared by the whole team. The app shows the cost before you confirm.
        </li>
        <li>
          <strong>Monthly credits.</strong>{" "}Each plan gives a monthly allowance of credits at the start of every
          billing period. At renewal the new allowance replaces what is left of the old one: unused monthly credits
          don&apos;t carry over. When a subscription ends, its remaining monthly credits end with it.
        </li>
        <li>
          <strong>Credit packs.</strong>{" "}Packs are one-off purchases that add credits on top of your plan. They are
          sold only to teams with an active paid subscription, not during the free trial or after a plan has ended.
          Purchased credits don&apos;t expire while your account exists, and they stay on the account if your plan
          ends, but downloading results needs an active plan.
        </li>
        <li>
          <strong>Which credits are used first.</strong>{" "}A job uses your monthly credits first and purchased
          credits only when the monthly ones run out.
        </li>
        <li>
          <strong>AI edits.</strong>{" "}Each page of a document includes 5 AI edits on that document. After that,
          every 5 further AI edits use 1 credit. Editing the text yourself is always free.
        </li>
        <li>
          <strong>Regenerate.</strong>{" "}You can regenerate a document up to 3 times. The first time is free; each
          later one uses one credit per page. A regenerate that fails is refunded and doesn&apos;t count towards the
          3.
        </li>
        <li>
          <strong>Re-running a translation.</strong>{" "}Translating the whole document again is charged like a new
          upload: one credit per page.
        </li>
        <li>
          <strong>Failed jobs.</strong>{" "}If a translation fails, for example because of a system error or because
          the document is already in the target language, the credits it used are refunded automatically to the
          balance they came from.
        </li>
        <li>
          Credits are not refunded for a translation that completed, even if you are unhappy with the AI draft: the
          draft is meant to be reviewed and edited (see section 9).
        </li>
        <li>Credits have no cash value and can&apos;t be transferred to another team.</li>
      </ul>
      <p>The plans and packs on sale today:</p>
      <PlanTable />
      <p>The prices shown when you buy are the ones that apply to that purchase.</p>

      <h2 id="vat">6. Prices and VAT</h2>
      <p>
        Prices are in euro (EUR). We are not registered for VAT, so no VAT is added: the price you see is the price
        you pay. Your bank may charge its own fees for paying in euro.
      </p>
      <p>
        Checkout asks for your billing address, which appears on your invoices. You are responsible for giving us
        correct billing details.
      </p>

      <h2 id="billing">7. Billing, renewal and cancellation</h2>
      <ul>
        <li>Payments are processed by Stripe, by card. We don&apos;t see or store your card details.</li>
        <li>
          Subscriptions are billed monthly in advance and renew automatically until you cancel. By subscribing you
          authorise Stripe to charge your card at each renewal, and for any credit pack you buy.
        </li>
        <li>
          The owner and team admins can change plan, update the card and billing details, download invoices and
          cancel in the billing portal, reachable from the Billing page.
        </li>
        <li>
          If you cancel, the cancellation takes effect at the end of the current billing period. You keep your plan
          and its credits until then, and you won&apos;t be charged again.
        </li>
        <li>
          A plan change takes effect straight away. Stripe works out the price difference for the rest of the
          current period and adds it to, or takes it off, your next invoice. On an upgrade you get the extra monthly
          credits at once. On a downgrade you keep the credits you already have, and the smaller allowance starts
          at your next renewal.
        </li>
        <li>
          If a payment fails, we may limit your account until it is paid. If we change a plan&apos;s price, we will
          tell you before it applies to your next renewal, and you can cancel before then.
        </li>
      </ul>

      <h2 id="refunds">8. Refunds</h2>
      <p>
        Credits that have been used, and subscription periods that have started, are not refunded, except where the
        law requires it. Failed jobs are refunded in credits as described in section 5.
      </p>
      <p>
        If you are a consumer in the UK or the EU, you have a 14-day right to withdraw from a purchase. By starting to use the
        service within those 14 days, for example by translating a page, you ask us to start providing it straight
        away. If you then withdraw, you pay for what you have already used, and the right of withdrawal no longer
        applies once the purchased service has been fully provided.
      </p>

      <h2 id="responsibility">9. Your professional responsibility</h2>
      <p>
        <strong>
          You, the translator or agency using OnlineDocTranslator, are solely responsible for every translation you
          deliver.
        </strong>{" "}
        That covers:
      </p>
      <ul>
        <li>the accuracy and completeness of the translation;</li>
        <li>any certification, sworn statement, affidavit or other official declaration you make about it;</li>
        <li>the stamps, seals and signatures you apply to it, including those you store in the service;</li>
        <li>
          following the professional, legal and regulatory rules that apply to you, and the requirements of the
          authority or person who will receive the translation.
        </li>
      </ul>
      <ul>
        <li>
          <strong>We provide a tool, not translation services.</strong>{" "}Neither OnlineDocTranslator nor{" "}
          {COMPANY.name} translates, checks or certifies your documents, or takes on any professional duty towards
          you or your clients.
        </li>
        <li>
          <strong>The output is a draft.</strong>{" "}AI translations can contain errors, omissions or misreadings,
          especially on scanned or handwritten documents. As a professional you must review and correct every
          translation before you use or deliver it.
        </li>
        <li>
          <strong>Certification is your act.</strong>{" "}OnlineDocTranslator never certifies a translation. Signing a
          certification, a sworn statement or an affidavit is your professional act, made under your own credentials
          and responsibility.
        </li>
        <li>
          Whether a receiving authority accepts a translation depends on your qualifications and its rules, not on us.
        </li>
        <li>
          <strong>Your clients are your clients.</strong>{" "}We are not a party to your relationship with your
          clients, to the price you agree with them, or to the payments they make to you. You deal with their
          questions, complaints, refunds and disputes.
        </li>
      </ul>

      <h2 id="indemnity">10. Claims by your clients</h2>
      <p>
        If one of your clients, or anyone else who relies on a translation you delivered, makes a claim against us
        about that translation, its certification, the stamps or signatures on it, or a payment between you and
        them, you agree to cover our reasonable losses and costs from that claim, including reasonable legal fees.
        This doesn&apos;t apply to the extent the claim was caused by our own breach of these terms or our
        negligence. We will tell you about the claim promptly and let you take part in handling it.
      </p>

      <h2 id="links">11. Client delivery links and payments</h2>
      <p>
        You can send a client a download link for a finished document. Anyone who has the link can open it until it
        expires or you revoke it, so share it only with the right person.
      </p>
      <p>
        A <strong>protected</strong>{" "}link shows the client a blurred, watermarked preview and serves the clean file
        only once the link is unlocked. Your client can pay you in one of these ways:
      </p>
      <ul>
        <li>
          <strong>Card, through Stripe.</strong>{" "}The payment is made on your own Stripe account, connected in
          Settings → Payments, and the money goes straight to you. The link unlocks automatically when Stripe
          confirms the payment. Your use of Stripe is governed by Stripe&apos;s own terms, including the Stripe
          Connected Account Agreement, between you and Stripe.
        </li>
        <li>
          <strong>PayPal.</strong>{" "}The client pays your PayPal.me link directly. The money goes straight to you,
          and PayPal&apos;s terms apply between you and PayPal.
        </li>
        <li>
          <strong>Another method</strong>, such as a bank transfer, agreed between you and your client outside the
          service.
        </li>
      </ul>
      <ul>
        <li>
          We don&apos;t receive, hold or pass on these payments, and we currently take no fee on them; we will tell you in advance before that changes. We are not your payment
          provider. Refunds, chargebacks, disputes, invoices and tax on these payments are for you to handle.
        </li>
        <li>
          For PayPal and other methods, the client can tell you they have paid, and we email you. It is your decision
          whether and when to unlock the link, and you are responsible for checking the money has arrived. We
          don&apos;t verify these payments, and we are not responsible if you unlock a link that wasn&apos;t paid, or
          don&apos;t unlock one that was.
        </li>
        <li>
          We don&apos;t collect or store your clients&apos; names or email addresses for these links. See the{" "}
          <Link href="/privacy#data">Privacy Policy</Link>{" "}for what we do record.
        </li>
      </ul>

      <h2 id="use">12. Acceptable use</h2>
      <p>You agree not to:</p>
      <ul>
        <li>upload content you have no right to process, or content that is illegal;</li>
        <li>use the service to forge documents or to mislead any authority;</li>
        <li>infringe anyone&apos;s intellectual property, privacy or confidentiality through the service;</li>
        <li>upload malware, or try to break, overload or get around the service&apos;s security or credit limits;</li>
        <li>try to access other customers&apos; accounts or data, or parts of the service you aren&apos;t allowed to use;</li>
        <li>
          copy, resell or reverse-engineer the service, or access it with bots, scrapers or other automated means we
          haven&apos;t allowed;
        </li>
        <li>use the service in breach of the usage policies of the AI providers we rely on.</li>
      </ul>

      <h2 id="content">13. Your content</h2>
      <ul>
        <li>
          You keep all rights in the documents you upload and the translations you produce. We claim no ownership.
        </li>
        <li>
          You give us a limited, non-exclusive permission to store, process and transmit your content, including to
          the sub-processors listed in the Privacy Policy, only as needed to provide the service to you. It ends when
          the content is deleted.
        </li>
        <li>
          You confirm you have the right to upload each document, including a lawful basis for any personal data in
          it. For that data you are the controller and we are your processor; a data processing agreement is
          available on request (see the Privacy Policy).
        </li>
      </ul>

      <h2 id="ai">14. AI providers and training</h2>
      <ul>
        <li>
          The AI work is done by Anthropic, and by OpenAI when someone in your team chooses an OpenAI engine, through
          their commercial APIs. Their output can be wrong, which is why section 9 applies.
        </li>
        <li>
          We don&apos;t use your content to train AI models. Under the providers&apos; commercial API terms, they
          don&apos;t train their models on it either. What the service learns from your corrections (translation
          memory, glossary, templates) stays within your team.
        </li>
      </ul>

      <h2 id="ours">15. Our service and brand</h2>
      <p>
        The OnlineDocTranslator software, website, design and name belong to us or our licensors. While your account
        is active, we give you a personal, non-exclusive, non-transferable right to use the service under these
        terms. Nothing else in the service is licensed to you.
      </p>

      <h2 id="confidentiality">16. Confidentiality</h2>
      <p>
        We treat your content as confidential. We access it only when needed to provide the service, to help you
        when you ask for support, to keep the service secure, or when the law requires it.
      </p>

      <h2 id="data">17. Storing and deleting your files</h2>
      <ul>
        <li>
          Projects are deleted automatically 90 days after the translation is completed. A project that never
          completes is deleted 90 days after it was uploaded. Running a translation again starts the 90 days again.
          Projects that already existed when automatic deletion began get the full 90 days from that date.
        </li>
        <li>
          Deletion covers the uploaded original, the translated and exported files, saved versions, page images,
          certified copies, delivery links and their files, and the project&apos;s text, segments and comments. The
          project and job pages show the date, and the uploader and the assignee get a notice 7 days before.
        </li>
        <li>
          Your team&apos;s translation memory, glossary and saved templates are kept, because they are your
          team&apos;s working assets. Memory entries and templates contain text from your documents. They stay until
          you delete them or the account.
        </li>
        <li>You can delete a project yourself at any time before then.</li>
        <li>
          The file behind a delivery link is deleted when you revoke the link, or 7 days after it expires.
        </li>
        <li>
          Deleting a project, or your account, deletes the stored files behind it. Invoices and accounting records
          are kept for as long as the law requires.
        </li>
        <li>
          The <Link href="/privacy#retention">Privacy Policy</Link>{" "}gives the full retention details. Keep your own
          copies of finished work.
        </li>
      </ul>

      <h2 id="availability">18. Availability and changes to the service</h2>
      <p>
        We work to keep OnlineDocTranslator available and reliable, but we don&apos;t guarantee uninterrupted service and
        offer no service level agreement (SLA). We may need maintenance windows. We may improve, change or remove
        features; if a change takes away something important you pay for, we will tell you in advance. If we decide
        to close the service altogether, we will give you reasonable notice so you can download your work.
      </p>

      <h2 id="warranty">19. What we promise, and what we don&apos;t</h2>
      <p>
        We will provide the service with reasonable care and skill. Beyond that, and as far as the law allows, the
        service is provided as it is: we don&apos;t promise that AI output will be accurate or complete, that the
        service will suit a particular purpose, or that an authority will accept a translation made with it.
      </p>
      <p>
        If you are a consumer, you keep your legal rights under the UK Consumer Rights Act 2015 and similar laws
        where you live, for example that digital content and services must be as described and of satisfactory
        quality. Nothing in these terms takes those rights away.
      </p>

      <h2 id="liability">20. Limitation of liability</h2>
      <ul>
        <li>
          We are not liable for indirect or consequential loss, such as lost profits, lost business or harm to
          reputation, or for loss caused by translations you did not review.
        </li>
        <li>
          Our total liability for any claim relating to the service is limited to the amount you paid us in the 12
          months before the claim.
        </li>
        <li>
          If you are a consumer, we are responsible for loss you suffer that was a foreseeable result of our breaking
          these terms or failing to use reasonable care and skill. We are not responsible for loss that was not
          foreseeable.
        </li>
        <li>
          Nothing in these terms limits or excludes liability for death or personal injury caused by negligence,
          for fraud or fraudulent misrepresentation, for wilful misconduct or gross negligence, or any other
          liability that cannot be limited by law, including your rights as a consumer.
        </li>
      </ul>

      <h2 id="termination">21. Suspension and termination</h2>
      <ul>
        <li>
          You can stop using the service at any time: cancel your subscription and delete your account in Settings.
        </li>
        <li>
          If the owner of a team deletes their account, the team&apos;s subscription is cancelled at once rather than
          at the end of the period. The rest of the period is not refunded, except where the law requires it.
        </li>
        <li>
          We may suspend or close an account that seriously or repeatedly breaks these terms, or where the law
          requires it. We will warn you first, unless we have to act at once, for example to stop illegal content,
          a security threat or harm to other users.
        </li>
        <li>
          When an account is deleted, its data is deleted as described in the Privacy Policy, and any remaining
          credits are lost.
        </li>
        <li>
          Sections 9, 10, 13, 15, 19, 20 and 22 continue to apply after your account ends.
        </li>
      </ul>

      <h2 id="law">22. Governing law and courts</h2>
      <p>
        These terms are governed by the law of England and Wales. The courts of England and Wales have jurisdiction
        over any dispute.
      </p>
      <p>
        If you are a consumer, you keep the protection of the mandatory laws of the country where you live, and you
        can bring a claim in the courts of your place of residence.
      </p>

      <h2 id="changes">23. Changes to these terms</h2>
      <p>
        We may update these terms. For changes that matter, we will tell you by email or in the app at least 30
        days before they take effect. If you don&apos;t agree, you can cancel before then. Continuing to use the
        service after that date means you accept the new terms. Smaller changes, such as clarifications, may apply
        sooner; the date at the top shows the latest version.
      </p>

      <h2 id="contact">24. Contact</h2>
      <p>
        {COMPANY.name}, {COMPANY.address}. Email:{" "}
        <a href={`mailto:${COMPANY.email}`}>{COMPANY.email}</a>. For questions about personal data, see the contact
        details in the{" "}
        <Link href="/privacy#contact">Privacy Policy</Link>.
      </p>
    </LegalPage>
  )
}
