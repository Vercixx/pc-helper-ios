//
//  index.swift
//  Extension entry point.
//

import SwiftUI
import WidgetKit

@main
struct PCUnlockWidgetBundle: WidgetBundle {
  var body: some Widget {
    StatusWidget()
    // Controls are iOS 18+; on anything older the bundle just ships the widget.
    if #available(iOS 18.0, *) {
      WakeControl()
    }
  }
}
