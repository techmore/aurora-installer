#if os(macOS)
  public enum MacPowerButtonGuide: String, Equatable, Sendable {
    case notebook, desktopRear, desktopUnderside, generic

    public init(deviceIdentifier: String, modelIdentifier: String) {
      // The 2024 mini moved its power button to the underside. Check the
      // enclosure before the broad Mac mini family match below.
      if ["Mac16,10", "Mac16,11"].contains(modelIdentifier) {
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
      case .desktopUnderside: "M4MiniPowerButton"
      case .generic: nil
      }
    }

    public var location: String {
      switch self {
      case .notebook: "The power button is at the top-right of the keyboard."
      case .desktopRear: "The power button is on the back of your Mac."
      case .desktopUnderside:
        "The power button is underneath your Mac mini, at the back corner below the Thunderbolt ports."
      case .generic: "Use the power button on your Mac."
      }
    }

    public var holdInstruction: String {
      switch self {
      case .desktopRear:
        "Press and hold the rear power button. \(PlainLanguage.startupOptionsHold)"
      case .desktopUnderside:
        "Press and hold the underside power button. \(PlainLanguage.startupOptionsHold)"
      case .notebook, .generic:
        "Press and hold the power button. \(PlainLanguage.startupOptionsHold)"
      }
    }
  }
#endif
