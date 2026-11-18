import AuroraAppleInstallerTrustCore
import AuroraInstallerUXCore
import SwiftUI

/// A red banner across the top of every window and sheet of the M4
/// local-payload test build, so it can never be mistaken for the official
/// installer. Other builds show nothing.
struct M4TestBuildBanner: View {
  var body: some View {
    Text(InstallerM4TestBuildGuard.bannerText)
      .font(.system(size: 18, weight: .heavy))
      .foregroundStyle(.white)
      .multilineTextAlignment(.center)
      .frame(maxWidth: .infinity)
      .padding(.vertical, 10)
      .padding(.horizontal, 12)
      .background(Color.red)
      .accessibilityIdentifier("m4-test-build-banner")
  }
}

extension View {
  @ViewBuilder func m4TestBuildBanner() -> some View {
    if InstallerM4TestBuildGuard.isActive {
      safeAreaInset(edge: .top, spacing: 0) { M4TestBuildBanner() }
    } else {
      self
    }
  }
}

/// The main window's title in this build.
enum M4TestBuildWindowTitle {
  static var title: String {
    InstallerM4TestBuildGuard.isActive
      ? InstallerM4TestBuildGuard.windowTitle : PlainLanguage.windowTitle
  }
}
