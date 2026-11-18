import XCTest

@testable import AuroraAppleInstallerTrustCore

final class InstallerM4TestBuildGuardTests: XCTestCase {
  private let expectedName = "nixos-kde-build-43451965403.zip"
  private let expectedDigest =
    "sha256:9c066b160de50c50e48a79e24d9a6deafc39f581f387c0cab68587419c4b7b61"

  func testActiveOnlyInTheDebugLocalPayloadTestBuild() {
    #if DEBUG
      let expected = ProcessInfo.processInfo.environment["AURORA_LOCAL_PAYLOAD_TEST_BUILD"] == "1"
    #else
      let expected = false
    #endif
    XCTAssertEqual(InstallerM4TestBuildGuard.isActive, expected)
  }

  func testOnlyTheGatedPayloadPasses() throws {
    XCTAssertEqual(InstallerM4TestBuildGuard.expectedPayloadFileName, expectedName)
    XCTAssertEqual(InstallerM4TestBuildGuard.expectedPayloadDigest, expectedDigest)
    try InstallerM4TestBuildGuard.checkPlannedPayload(
      fileName: expectedName, digest: expectedDigest, active: true)
    try InstallerM4TestBuildGuard.checkPlannedPayload(
      fileName: expectedName,
      digest: expectedDigest.uppercased().replacingOccurrences(
        of: "SHA256:", with: "sha256:"), active: true)
    let official = "sha256:b1214f18823900000000000000000000000000000000000000000000006dc3"
    for (name, digest) in [
      ("nixos-kde-build-43697993510.zip", official),
      (expectedName, official),
      ("nixos-kde-build-43697993510.zip", expectedDigest),
    ] {
      XCTAssertThrowsError(
        try InstallerM4TestBuildGuard.checkPlannedPayload(
          fileName: name, digest: digest, active: true)
      ) {
        XCTAssertEqual(
          $0 as? InstallerM4TestBuildGuard.Refusal, .otherPayload(fileName: name, digest: digest))
        XCTAssertTrue(String(describing: $0).contains("M4 TEST BUILD refused"))
      }
      // Inactive builds never refuse.
      try InstallerM4TestBuildGuard.checkPlannedPayload(
        fileName: name, digest: digest, active: false)
    }
  }

  func testDownloadsOfFiveGigabytesOrMoreAreRefused() throws {
    try InstallerM4TestBuildGuard.checkDownload(
      fileName: "installer-data-nixos-kde.json", sizeBytes: 4_999_999_999, active: true)
    for size: UInt64 in [5_000_000_000, 5_910_000_000, UInt64.max] {
      XCTAssertThrowsError(
        try InstallerM4TestBuildGuard.checkDownload(
          fileName: "nixos-kde-build-43697993510.zip", sizeBytes: size, active: true)
      ) {
        XCTAssertEqual(
          $0 as? InstallerM4TestBuildGuard.Refusal,
          .largeDownload(fileName: "nixos-kde-build-43697993510.zip", sizeBytes: size))
      }
      try InstallerM4TestBuildGuard.checkDownload(
        fileName: "nixos-kde-build-43697993510.zip", sizeBytes: size, active: false)
    }
  }

  func testBannerNamesTheBuild() {
    XCTAssertEqual(
      InstallerM4TestBuildGuard.bannerText, "M4 TEST BUILD — local payload 9c066b16… — 27.2 stub")
    XCTAssertTrue(InstallerM4TestBuildGuard.windowTitle.contains("M4 TEST BUILD"))
  }
}
