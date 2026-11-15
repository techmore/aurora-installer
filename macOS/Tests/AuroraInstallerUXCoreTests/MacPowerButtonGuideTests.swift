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
        XCTAssertTrue(guide.location.contains("Thunderbolt"))
        XCTAssertTrue(guide.holdInstruction.contains("underside"))
        assertNamesBothMessagesInOrder(guide.holdInstruction)
      }
    }

    func testRearAndGenericGuidesNameBothMessages() {
      for guide in [MacPowerButtonGuide.desktopRear, .notebook, .generic] {
        assertNamesBothMessagesInOrder(guide.holdInstruction)
      }
    }

    func testEveryHoldInstructionNamesBothMessagesInOrder() {
      var texts = [
        PlainLanguage.stage1CautionRecovery, PlainLanguage.shutdownConfirmationBody,
        PlainLanguage.bootLoaderShutdownBody,
      ]
      texts += PlainLanguage.recoverySteps(for: [])
        .filter { $0.title == "Hold the power button" }.compactMap(\.detail)
      texts += PlainLanguage.bootLoaderUpdateRecoverySteps()
        .filter { $0.title == "Hold the power button" }.compactMap(\.detail)
      XCTAssertEqual(texts.count, 5)
      for text in texts {
        assertNamesBothMessagesInOrder(text)
        XCTAssertFalse(text.contains("until startup options appear"), text)
      }
    }

    private func assertNamesBothMessagesInOrder(
      _ text: String, file: StaticString = #filePath, line: UInt = #line
    ) {
      guard let first = text.range(of: "“Continue holding for startup options”"),
        let second = text.range(of: "“Loading startup options”")
      else {
        return XCTFail("missing a startup-options message: \(text)", file: file, line: line)
      }
      XCTAssertLessThan(first.lowerBound, second.lowerBound, text, file: file, line: line)
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
