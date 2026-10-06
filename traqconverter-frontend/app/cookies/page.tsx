import type { Metadata } from "next"
import Link from "next/link"

import LegalPage, { TableScroll } from "@/components/legal/LegalPage"

export const metadata: Metadata = {
  title: "Cookie Policy · OnlineDocTranslator",
  description: "What OnlineDocTranslator stores in your browser, and why.",
}

export default function CookiesPage() {
  return (
    <LegalPage
      title="Cookie Policy"
      intro="OnlineDocTranslator sets no cookies and runs no analytics or advertising trackers. It stores only what it needs to keep you signed in and remember a setting you chose."
    >
      <h2 id="what">1. What we store in your browser</h2>
      <p>
        Instead of cookies, the app uses your browser&apos;s local storage and session storage. These are strictly
        necessary for the service you asked for, so they don&apos;t need your consent and there is no cookie banner.
      </p>
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Where</th>
              <th>Purpose</th>
              <th>How long</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <code>token</code>
              </td>
              <td>Session storage, or local storage if you tick &quot;Remember me&quot;</td>
              <td>Keeps you signed in</td>
              <td>Until you sign out, or close the browser if you didn&apos;t tick &quot;Remember me&quot;</td>
            </tr>
            <tr>
              <td>
                <code>remember</code>
              </td>
              <td>Local storage</td>
              <td>Remembers that you chose &quot;Remember me&quot;</td>
              <td>Until you sign out</td>
            </tr>
            <tr>
              <td>
                <code>tq.lastTargetLanguage</code>
              </td>
              <td>Local storage</td>
              <td>Pre-selects the target language you used last for a new project</td>
              <td>Until you clear your browser data</td>
            </tr>
          </tbody>
        </table>
      </TableScroll>
      <p>None of these items is shared with third parties or used to track you across websites.</p>

      <h2 id="third-parties">2. Third-party pages</h2>
      <p>
        We load no third-party scripts, and our fonts are served from our own site. When you pay or manage your
        subscription, you go to pages hosted by Stripe (Checkout and the billing portal). Stripe sets its own cookies
        there, for example to prevent fraud. Those are covered by Stripe&apos;s own cookie policy.
      </p>

      <h2 id="logs">3. Server logs</h2>
      <p>
        Like any website, our hosting providers record technical data such as your IP address when your browser
        requests a page. This is not stored in your browser; see the <Link href="/privacy">Privacy Policy</Link>.
      </p>

      <h2 id="control">4. How to remove them</h2>
      <p>
        Signing out deletes the sign-in items. You can also clear all of them in your browser settings by deleting
        the site data for OnlineDocTranslator. If you do, you&apos;ll need to sign in again.
      </p>

      <h2 id="changes">5. Changes</h2>
      <p>
        If we ever add analytics or any storage that isn&apos;t strictly necessary, we will ask for your consent
        first and update this page.
      </p>
    </LegalPage>
  )
}
