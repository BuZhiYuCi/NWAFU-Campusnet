// 依赖统一走腾讯云镜像：实测 1.3MB/s，直连 dl.google.com 只有 220KB/s。
// 镜像完整代理了 Google Maven + Maven Central + Gradle 插件标记，
// 未命中时会自动回落到下面的官方仓库。
//
// 注意：pluginManagement 块会被单独编译，外层变量在其中不可见，URL 必须内联。
pluginManagement {
    repositories {
        maven("https://mirrors.cloud.tencent.com/nexus/repository/maven-public/") {
            name = "TencentMirror"
        }
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        maven("https://mirrors.cloud.tencent.com/nexus/repository/maven-public/") {
            name = "TencentMirror"
        }
        google()
        mavenCentral()
    }
}

rootProject.name = "CampusNet"
include(":app")
