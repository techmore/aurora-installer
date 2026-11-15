#if os(macOS)
  import XCTest
  @testable import AuroraInstallerUXCore

  final class MacPowerButtonGuideTests: XCTestCase {
    func testNotebookAndCompactDesktopSelection() {
      for id in ["apple,j293", "apple,j413", "apple,j414s", "apple,j700"] {
        XCTAssertEqual(MacPowerButtonGuide(deviceIdentifier: id, modelIdentifier: ""), .notebook)
      }
      for id in ["apple,j274", "apple,j473", "apple,j474s", "apple,j375c", "apple,j475d"] {
        XCTAssertEqual(MacPowerButtonGuide(deviceIdentifier: id, modelIdentifier: ""), .desktopRear)
      }
    }

    func testM4MiniUsesUndersideButtonArtworkBeforeFamilyMatch() {
      for (device, model) in [("apple,j773g", "Mac16,10"), ("apple,j773s", "Mac16,11")] {
        let guide = MacPowerButtonGuide(deviceIdentifier: device, modelIdentifier: model)
        XCTAssertEqual(guide, .desktopUnderside)
        XCTAssertEqual(guide.assetName, "M4MiniPowerButton")
        XCTAssertTrue(guide.location.contains("rear-left"))
        XCTAssertTrue(guide.holdInstruction.contains("underside"))
        XCTAssertTrue(guide.holdInstruction.contains("Continue holding for startup options"))
        XCTAssertTrue(guide.holdInstruction.contains("Loading startup options"))
      }
    }

    func testUnknownAndOtherEnclosuresUseGenericGuidance() {
      for id in ["unknown", "apple,j456", "apple,j180d"] {
        let guide = MacPowerButtonGuide(deviceIdentifier: id, modelIdentifier: "unknown")
        XCTAssertEqual(guide, .generic)
        XCTAssertNil(guide.assetName)
      }
    }
  }
#endif
