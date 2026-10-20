// Original moving light rings, adapted as a standalone Qt Quick 2.4 component.
import QtQuick 2.4

Item {
    id: field
    objectName: "ringField"
    property bool playing: false
    property bool liteMode: false
    property bool isPartial: false
    property string guideString: ""
    signal looped()
    property real phase: 0
    property real seed: Math.random()
    property bool initialized: false
    readonly property real scaleUnit: Math.max(0.35, Math.min(width / 1920, height / 1080))
    readonly property real envelope: Math.max(0, Math.min(1, phase * 7.5, (1 - phase) * 6.0))
    readonly property int ringCount: isPartial ? 2 : (liteMode ? 3 : 5)
    clip: true

    function updatePlaying() {
        if (!initialized) return;
        if (playing) {
            visible = true;
            phase = 0;
            drift.restart();
            cycleTimer.restart();
        } else {
            cycleTimer.stop();
            drift.stop();
            phase = 0;
            visible = false;
        }
    }
    onPlayingChanged: updatePlaying()
    Component.onCompleted: { initialized = true; updatePlaying(); }
    NumberAnimation {
        id: drift
        objectName: "ringDrift"
        target: field
        property: "phase"
        from: 0
        to: 1
        duration: 7500
        easing.type: Easing.Linear
    }
    Timer {
        id: cycleTimer
        objectName: "cycleTimer"
        interval: 7500
        repeat: false
        onTriggered: { if (field.playing) field.looped(); }
    }
    Repeater {
        model: field.ringCount
        Item {
            id: orbit
            objectName: "movingRing"
            property real theta: (field.seed * 6.2831853) + index * 1.2566371 + field.phase * 0.45
            property real diameter: (215 + index * 35) * field.scaleUnit
            property color tint: index % 3 === 0 ? "#53cbd7" : (index % 3 === 1 ? "#c09aff" : "#f4b784")
            width: diameter
            height: diameter
            x: field.width * 0.5 - width * 0.5 + Math.cos(theta) * Math.max(0, field.width * 0.31 - width * 0.25)
            y: field.height * 0.5 - height * 0.5 + Math.sin(theta * 1.13) * Math.max(0, field.height * 0.25 - height * 0.18)
            opacity: field.envelope
            rotation: -32 + index * 23 + field.phase * 9
            transform: Scale { origin.x: orbit.width * 0.5; origin.y: orbit.height * 0.5; xScale: 1; yScale: 0.63 + (index % 3) * 0.12 }
            Rectangle {
                anchors.fill: parent
                radius: width / 2
                color: "transparent"
                border.width: Math.max(3, 12 * field.scaleUnit)
                border.color: orbit.tint
                opacity: 0.045
                antialiasing: true
            }
            Rectangle {
                anchors.fill: parent
                anchors.margins: 2 * field.scaleUnit
                radius: width / 2
                color: "transparent"
                border.width: Math.max(1, 3.0 * field.scaleUnit)
                border.color: orbit.tint
                opacity: 0.72
                antialiasing: true
            }
        }
    }
}
