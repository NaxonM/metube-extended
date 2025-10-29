from playwright.sync_api import Page, expect

def test_concurrent_downloads_setting(page: Page):
    """
    This test verifies that the concurrent downloads setting can be updated in the admin dashboard.
    """
    # 1. Arrange: Go to the admin page.
    page.goto("http://localhost:8081/admin/system")

    # 2. Act: Find the input field and change the value.
    downloads_input = page.get_by_label("Max Concurrent Downloads")
    downloads_input.fill("5")

    # 3. Screenshot: Capture the change.
    page.screenshot(path="jules-scratch/verification/concurrent-downloads.png")

    # 4. Act: Click the save button.
    save_button = page.get_by_role("button", name="Save")
    save_button.click()

    # 5. Assert: Verify that the value was saved.
    expect(downloads_input).to_have_value("5")
