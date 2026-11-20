# Chrome connection proof (developer diagnostic)

For student installation and browser sign-in, use the [npm launcher guide](../README.md). You do not need this extension to use the local MCP server.

This unpacked Chrome extension tests whether Union's normal Nexus/Okta login can provide the API access required by the read-only MCP tools. It does not save a credential, configure a desktop MCP client, or enroll a user in the hosted ChatGPT connector.

## Run the proof

1. Check out the repository and open `chrome://extensions` in Chrome.
2. Enable **Developer mode**, choose **Load unpacked**, and select this `extension` directory.
3. Click the extension's **Connect Union Nexus** action.
4. Check the consent box and click **Open Nexus login**.
5. Sign in through the real Nexus/Okta page with your Union account and MFA.
6. Return to the extension connection page and click **I've finished signing in**.
7. Confirm it reports your name and all 12 required APIs. If it fails, record the displayed diagnostic code without sharing credentials or callback URLs.
8. Remove the unpacked extension after testing.

The credential stays in extension memory and is sent only to Nexus to validate identity and API permissions. It is not stored or sent to Descope, Vercel, ChatGPT, or Codex. Nexus may reuse a mobile-app token or create one if none exists; the proof does not open token management or reset a token. Closing the proof does not revoke a Nexus-issued token.

## Checks and status

With Node.js 20 or newer, from the repository root:

```sh
node --test extension/test_*.mjs
```

No npm install is needed for these dependency-free tests. The owner-account live proof passed September 23, 2026; a second live student account remains unverified. See the [release record](../RELEASE.md) for the evidence and remaining release gates.
