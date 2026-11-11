#if os(macOS)
  public enum MacPowerButtonGuide: String, Equatable, Sendable {
    case notebook, desktopRear, desktopUnderside, generic

    // Apple's 2024 mini (M4, M4 Pro) moved its power button to the underside.
    // This is presentation metadata, not an installation support gate.
    private static let undersideDevices: Set<String> = ["apple,j773g", "apple,j773s"]
    private static let undersideModels: Set<String> = ["Mac16,10", "Mac16,11"]

    public init(deviceIdentifier: String, modelIdentifier: String) {
      // Checked before the family: the 2024 mini is a "Mac mini" too.
      if Self.undersideModels.contains(modelIdentifier)
        || Self.undersideDevices.contains(deviceIdentifier.lowercased())
      {
        self = .desktopUnderside
        return
      }
      switch MacModelNames.entry(for: deviceIdentifier)?.family {
      case "MacBook Air", "MacBook Pro", "MacBook Neo": self = .notebook
      case "Mac mini", "Mac Studio": self = .desktopRear
      default: self = .generic
      }
    }

    public var assetName: String? {
      switch self {
      case .notebook: "MacBookPowerButton"
      case .desktopRear: "MacDesktopPowerButton"
      case .desktopUnderside, .generic: nil
      }
    }

    public var location: String {
      switch self {
      case .notebook: "The power button is at the top-right of the keyboard."
      case .desktopRear: "The power button is on the back of your Mac."
      case .desktopUnderside: "The power button is on the underside of your Mac mini."
      case .generic: "Use the power button on your Mac."
      }
    }

    public var holdInstruction: String {
      switch self {
      case .desktopRear: "Hold the rear power button until startup options appear."
      case .desktopUnderside: "Hold the underside power button until startup options appear."
      case .notebook, .generic: "Hold the power button until startup options appear."
      }
    }
  }
#endif
