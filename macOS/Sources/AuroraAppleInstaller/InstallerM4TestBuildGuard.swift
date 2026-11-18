import Foundation

/// The Mac16,10 local-payload test build (`AURORA_LOCAL_PAYLOAD_TEST_BUILD=1`,
/// debug configuration only) may install exactly one gated payload, and only
/// from the local test cache. It refuses any other payload the plan names and
/// any download of 5 GB or more, so it can never fall back to a public
/// release payload. Every other build compiles the guard as inactive.
public enum InstallerM4TestBuildGuard {
  public static let expectedPayloadFileName = "nixos-kde-build-43451965403.zip"
  public static let expectedPayloadDigest =
    "sha256:9c066b160de50c50e48a79e24d9a6deafc39f581f387c0cab68587419c4b7b61"
  /// Decimal 5 GB. The official Edge payload is 5.91 GB.
  public static let downloadLimitBytes: UInt64 = 5_000_000_000
  public static let bannerText = "M4 TEST BUILD — local payload 9c066b16… — 27.2 stub"
  public static let windowTitle =
    "Aurora Installer M4 TEST BUILD — local payload 9c066b16… — 27.2 stub"

  public static var isActive: Bool {
    #if DEBUG && AURORA_LOCAL_PAYLOAD_TEST_BUILD
      return true
    #else
      return false
    #endif
  }

  public enum Refusal: Error, Equatable, Sendable, CustomStringConvertible {
    case otherPayload(fileName: String, digest: String)
    case largeDownload(fileName: String, sizeBytes: UInt64)

    public var description: String {
      switch self {
      case .otherPayload(let fileName, let digest):
        return "M4 TEST BUILD refused: the plan names payload \(fileName) (\(digest)), "
          + "not \(InstallerM4TestBuildGuard.expectedPayloadFileName) "
          + "(\(InstallerM4TestBuildGuard.expectedPayloadDigest)). STOP and tell the lead."
      case .largeDownload(let fileName, let sizeBytes):
        return "M4 TEST BUILD refused to download \(fileName) (\(sizeBytes) bytes): "
          + "this build downloads nothing of 5 GB or more. STOP and tell the lead."
      }
    }
  }

  /// Throws when the plan's payload is not the one gated payload.
  public static func checkPlannedPayload(
    fileName: String, digest: String, active: Bool = isActive
  ) throws {
    guard active else { return }
    guard fileName == expectedPayloadFileName, digest.lowercased() == expectedPayloadDigest
    else { throw refuse(.otherPayload(fileName: fileName, digest: digest)) }
  }

  /// Throws before any network transfer of 5 GB or more.
  public static func checkDownload(
    fileName: String, sizeBytes: UInt64, active: Bool = isActive
  ) throws {
    guard active, sizeBytes >= downloadLimitBytes else { return }
    throw refuse(.largeDownload(fileName: fileName, sizeBytes: sizeBytes))
  }

  /// Both checks for one pinned catalog artifact.
  public static func check(
    _ artifact: PinnedInstallerArtifact, downloading: Bool, active: Bool = isActive
  ) throws {
    if artifact.role == "payload" {
      try checkPlannedPayload(
        fileName: artifact.fileName, digest: artifact.expectedDigest, active: active)
    }
    if downloading {
      try checkDownload(
        fileName: artifact.fileName, sizeBytes: artifact.expectedSizeBytes, active: active)
    }
  }

  private static func refuse(_ refusal: Refusal) -> Refusal {
    InstallerLog.error(refusal.description)
    return refusal
  }
}
