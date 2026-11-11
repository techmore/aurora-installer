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

    func testUndersideButtonDoesNotUseRearButtonArtwork() {
      for model in ["Mac16,10", "Mac16,11"] {
        let guide = MacPowerButtonGuide(deviceIdentifier: "unknown", modelIdentifier: model)
        XCTAssertEqual(guide, .desktopUnderside)
        XCTAssertNil(guide.assetName)
        XCTAssertTrue(guide.holdInstruction.contains("underside"))
      }
    }

    // The 2024 mini is in the "Mac mini" family, so a known device identifier
    // must not fall through to the rear-button artwork of the older minis.
    func testKnown2024MiniUsesUndersideButton() {
      let cases = [
        ("apple,j773g", "Mac16,10"), ("apple,j773s", "Mac16,11"),
        ("apple,j773g", ""), ("apple,j773s", ""),
      ]
      for (id, model) in cases {
        let guide = MacPowerButtonGuide(deviceIdentifier: id, modelIdentifier: model)
        XCTAssertEqual(guide, .desktopUnderside, "\(id) \(model)")
        XCTAssertNil(guide.assetName)
      }
    }

    func testOnlyDesktopsAskForAKeyboard() {
      XCTAssertNotNil(MacPowerButtonGuide.desktopRear.keyboardNote)
      XCTAssertNotNil(MacPowerButtonGuide.desktopUnderside.keyboardNote)
      XCTAssertNil(MacPowerButtonGuide.notebook.keyboardNote)
      XCTAssertNil(MacPowerButtonGuide.generic.keyboardNote)
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
