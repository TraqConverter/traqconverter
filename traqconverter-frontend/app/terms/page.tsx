import type { Metadata } from "next"
import Link from "next/link"

import LegalPage from "@/components/legal/LegalPage"
import PlanTable from "@/components/legal/PlanTable"
import { COMPANY, VAT_NOTE } from "@/lib/company"

export const metadata: Metadata = {
  title: "Terms of Service · TraqConverter",
  description: "The terms for using TraqConverter, sold by Espresso Translations S.r.l.",
}

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Service"
      intro="These terms are the agreement between you and us for using TraqConverter. We've kept them short and plain. Please read them before you sign up."
    >
      <h2 id="who">1. Who we are</h2>
      <p>
        TraqConverter is provided by {COMPANY.name}, P.IVA and codice fiscale {COMPANY.vat}, registered office{" "}
        {COMPANY.address}{" "}(&quot;we&quot;, &quot;us&quot;). By creating an account you accept these terms and
        confirm you have read our <Link href="/privacy">Privacy Policy</Link>.
      </p>

      <h2 id="service">2. The service</h2>
      <p>
        TraqConverter is an online workspace for professional translators and agencies. You upload a document (PDF,
        image or DOCX); the service produces an AI draft translation with the original layout rebuilt, which you
        review and edit. Depending on your plan it also offers translation memory, glossaries, templates,
        certification pages, client delivery links and team collaboration.
      </p>
      <p>You must be at least 18 to use the service.</p>

      <h2 id="accounts">3. Accounts and teams</h2>
      <ul>
        <li>Give accurate details when you sign up, and keep your password secret.</li>
        <li>You are responsible for what happens under your account.</li>
        <li>
          Every account belongs to a team. The person who creates the team is its owner. The owner can invite
          members, up to the team size of the plan, and assign their roles.
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
        can&apos;t download results, and some features (translation memory, glossary, templates, certifications)
        aren&apos;t available. No card is needed. When the trial ends, you need a paid plan to continue.
      </p>

      <h2 id="credits">5. Plans and credits</h2>
      <ul>
        <li>
          <strong>1 credit = 1 page.</strong>{" "}Translating a page uses one credit. A page credit also includes a set
          number of AI edits on that document; further AI edits use credits, as shown in the app.
        </li>
        <li>
          Each plan adds a monthly allowance of credits at the start of every billing period. Unused monthly credits
          don&apos;t carry over to the next period.
        </li>
        <li>
          Credit packs are one-off purchases that add credits on top of your plan. They are available to teams with
          an active paid subscription, not during the free trial or after a plan has ended. Credits you have already
          bought don&apos;t expire while your account exists.
        </li>
        <li>Credits have no cash value and can&apos;t be transferred to another team.</li>
      </ul>
      <p>The plans and packs on sale today:</p>
      <PlanTable />
      <p>The prices shown when you buy are the ones that apply to that purchase.</p>

      <h2 id="vat">6. Prices and VAT</h2>
      <p>
        Prices are in euro and exclude VAT. VAT is added at checkout where it applies, based on your billing address
        and VAT number. {VAT_NOTE}
      </p>
      <p>
        If you buy as a business, enter your VAT number at checkout. You are responsible for giving us correct billing
        and tax details.
      </p>

      <h2 id="billing">7. Billing, renewal and cancellation</h2>
      <ul>
        <li>Payments are processed by Stripe. We don&apos;t see or store your card details.</li>
        <li>Subscriptions are billed monthly in advance and renew automatically until you cancel.</li>
        <li>
          You can change plan, update your card and billing details, download invoices and cancel in the billing
          portal, reachable from the Billing page.
        </li>
        <li>
          If you cancel, the cancellation takes effect at the end of the current billing period. You keep your plan
          and its credits until then, and you won&apos;t be charged again.
        </li>
        <li>
          An upgrade takes effect straight away: you pay the difference for the rest of the period and get the extra
          credits. When you downgrade, you keep the credits you already have.
        </li>
        <li>
          If a payment fails, we may limit your account until it is paid. If we change a plan&apos;s price, we will
          tell you before it applies to your next renewal, and you can cancel before then.
        </li>
      </ul>

      <h2 id="refunds">8. Refunds</h2>
      <p>
        Credits that have been used, and subscription periods that have started, are not refunded, except where the
        law requires it.
      </p>
      <p>
        If you are a consumer in the EU, you have a 14-day right to withdraw from a purchase. By starting to use the
        service within those 14 days, for example by translating a page, you ask us to start providing it straight
        away. If you then withdraw, you pay for what you have already used, and the right of withdrawal no longer
        applies once the purchased service has been fully provided.
      </p>

      <h2 id="responsibility">9. Your professional responsibility</h2>
      <ul>
        <li>
          <strong>The output is a draft.</strong>{" "}AI translations can contain errors, omissions or misreadings,
          especially on scanned or handwritten documents. You must review every translation before you use or deliver
          it.
        </li>
        <li>
          <strong>Certification is your act.</strong>{" "}TraqConverter never certifies a translation. Signing a
          certification, a sworn statement or an affidavit is your professional act, made under your own credentials
          and responsibility.
        </li>
        <li>
          Whether a receiving authority accepts a translation depends on your qualifications and its rules, not on us.
        </li>
      </ul>

      <h2 id="use">10. Acceptable use</h2>
      <p>You agree not to:</p>
      <ul>
        <li>upload content you have no right to process, or content that is illegal;</li>
        <li>use the service to forge documents or to mislead any authority;</li>
        <li>upload malware, or try to break, overload or get around the service&apos;s security or credit limits;</li>
        <li>copy, resell or reverse-engineer the service, or access it by automated means we haven&apos;t allowed;</li>
        <li>use the service in breach of the usage policies of the AI providers we rely on.</li>
      </ul>

      <h2 id="content">11. Your content</h2>
      <ul>
        <li>
          You keep all rights in the documents you upload and the translations you produce. We claim no ownership.
        </li>
        <li>
          You give us permission to store, process and transmit your content, including to the sub-processors listed
          in the Privacy Policy, only as needed to provide the service to you.
        </li>
        <li>
          We don&apos;t use your content to train AI models. What the service learns from your corrections stays
          within your team.
        </li>
        <li>
          You confirm you have the right to upload each document, including a lawful basis for any personal data in
          it. For that data you are the controller and we are your processor; a data processing agreement is
          available on request (see the Privacy Policy).
        </li>
      </ul>

      <h2 id="confidentiality">12. Confidentiality</h2>
      <p>
        We treat your content as confidential. We access it only when needed to provide the service, to help you
        when you ask for support, to keep the service secure, or when the law requires it.
      </p>

      <h2 id="availability">13. Availability and changes to the service</h2>
      <p>
        We work to keep TraqConverter available and reliable, but we don&apos;t guarantee uninterrupted service and
        offer no service level agreement (SLA). We may need maintenance windows. We may improve, change or remove
        features; if a change takes away something important you pay for, we will tell you in advance. Keep your
        own copies of finished work.
      </p>

      <h2 id="liability">14. Limitation of liability</h2>
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
          Nothing in these terms limits liability for wilful misconduct or gross negligence, for death or personal
          injury, or any other liability that cannot be limited by law, including your rights as a consumer.
        </li>
      </ul>

      <h2 id="termination">15. Suspension and termination</h2>
      <ul>
        <li>
          You can stop using the service at any time: cancel your subscription and delete your account in Settings.
        </li>
        <li>
          We may suspend or close an account that seriously or repeatedly breaks these terms, or where the law
          requires it. Unless urgent, we will warn you first.
        </li>
        <li>
          When an account is deleted, its data is deleted as described in the Privacy Policy, and any remaining
          credits are lost.
        </li>
      </ul>

      <h2 id="law">16. Governing law and courts</h2>
      <p>
        These terms are governed by Italian law. The courts of Milan, Italy have exclusive jurisdiction over any
        dispute.
      </p>
      <p>
        If you are a consumer, you keep the protection of the mandatory laws of the country where you live, and you
        can bring a claim in the courts of your place of residence.
      </p>

      <h2 id="changes">17. Changes to these terms</h2>
      <p>
        We may update these terms. For changes that matter, we will tell you by email or in the app at least 30
        days before they take effect. If you don&apos;t agree, you can cancel before then. Continuing to use the
        service after that date means you accept the new terms.
      </p>

      <h2 id="contact">18. Contact</h2>
      <p>
        {COMPANY.name}, {COMPANY.address}. For questions about personal data, see the contact details in the{" "}
        <Link href="/privacy#contact">Privacy Policy</Link>.
      </p>
    </LegalPage>
  )
}
