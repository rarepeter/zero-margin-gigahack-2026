# Set up company billing on OpenRouter

## Choose the account that owns the credits

Use a company organization if several people need shared credits and billing. OpenRouter's [team setup guide](https://openrouter.ai/blog/tutorials/team-spend-controls-setup/) explains organization roles and shared credit pools. Confirm the active account before buying credits or creating the benchmark key.

If you only need company details on your invoices, use the billing form on your current account. Keep personal and company purchases separate according to your own accounting requirements.

## Add invoice details

1. Open [Credits](https://openrouter.ai/settings/credits) in the intended account.
2. Select **Add Credits**. If no billing address is saved, complete the **Add a Billing Address** dialog with the intended invoice name, country, and address.
3. Enable **Send me Invoices** on the purchase form.
4. Use **Edit Tax ID** to enter your company's tax or VAT identifier if applicable.
5. Use **Advanced invoicing** if you need a purchase order number or notes.
6. Review the invoice details, credit amount, and fees before completing payment. Leave automatic top-ups off unless you want recurring purchases.

OpenRouter documents the invoice and tax fields in [All about Invoices](https://openrouter.zendesk.com/hc/en-us/articles/40856014375451-All-about-Invoices). Existing invoices are available through **Payment History** on the Credits page.

## Create a benchmark key

1. Open the API Keys page in the account or workspace that should pay for the benchmark.
2. Create a separate key named `speechbench` with a spending limit appropriate for your tests.
3. Put the key in the app's `.env` file as `OPENROUTER_API_KEY`.
4. Restart the app. Confirm that its connection badge changes to **API key configured**. This badge confirms that a key is configured, not that its balance or permissions have been verified.
5. Run one model on a short recording first. Check the saved transcript, request settings, cost, and your OpenRouter activity before running the full comparison.

The app does not create an OpenRouter account, purchase credits, or store payment details. The company information and initial credit amount must be supplied by the account owner.
